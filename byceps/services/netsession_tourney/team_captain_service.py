"""
byceps.services.netsession_tourney.team_captain_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Teams managed by their captain: create, update, ready state.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .coin_service import (
    charge_coins_for_tournament_registration,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .models import (
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationMode,
    TeamMemberRole,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    refresh_match_states_for_participant_readiness,
)
from .registration_service import (
    ensure_registration_is_registered,
    generate_unique_invite_code_for_tournament,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .team_captain_service_ready import (
    _check_team_ready_state_change,
    count_team_members as count_team_members,
)
from .team_parts_membership import add_team_member
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)
from .tourney_registration_checks import validate_user_can_enter_tournament


def create_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    user: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    entry_error = validate_user_can_enter_tournament(
        party_id, tournament_id, tournament, user.id, check_capacity=True
    )
    if entry_error is not None:
        return Err(entry_error)

    charge_result = charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    invite_code = generate_unique_invite_code_for_tournament(tournament_id)
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.team,
        team_name.strip(),
        now,
        logo_url=team_logo_url.strip() if team_logo_url else None,
        manager_user_id=user.id,
        status=ParticipantStatus.forming,
        invite_code=invite_code,
    )
    db.session.add(db_participant)
    add_team_member(db_participant.id, user.id, TeamMemberRole.captain, now)
    ensure_registration_is_registered(tournament_id, user.id, created_at=now)

    append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created',
        payload={'invite_code': invite_code},
        created_at=now,
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def update_managed_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
    replace_logo: bool = False,
) -> Result[Participant, str]:
    managed_team_result = _load_managed_team_for_captain(
        party_id, tournament_id, participant_id, initiator.id
    )
    if managed_team_result.is_err():
        return Err(managed_team_result.unwrap_err())
    db_tournament, tournament, db_participant = managed_team_result.unwrap()

    if tournament.status == TournamentStatus.live:
        return _update_live_team_logo_for_captain(
            db_participant,
            participant_id,
            initiator,
            team_logo_url=team_logo_url,
            replace_logo=replace_logo,
        )

    return _update_team_for_captain(
        db_participant,
        participant_id,
        initiator,
        team_name,
        team_logo_url=team_logo_url,
        replace_logo=replace_logo,
    )


def _update_live_team_logo_for_captain(
    db_participant: DbNetsessionTourneyParticipant,
    participant_id: ParticipantID,
    initiator: User,
    *,
    team_logo_url: str | None,
    replace_logo: bool,
) -> Result[Participant, str]:
    if not replace_logo:
        return Err(
            'Während das Turnier läuft, lässt sich nur das Team-Logo ändern.'
        )

    db_participant.logo_url = _normalize_team_logo_url(team_logo_url)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_logo_updated_by_captain_while_live',
        payload={
            'logo_url': db_participant.logo_url,
            'replace_logo': replace_logo,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def _update_team_for_captain(
    db_participant: DbNetsessionTourneyParticipant,
    participant_id: ParticipantID,
    initiator: User,
    team_name: str,
    *,
    team_logo_url: str | None,
    replace_logo: bool,
) -> Result[Participant, str]:
    team_name_clean = team_name.strip()
    if not team_name_clean:
        return Err('Ein Teamname ist erforderlich.')

    db_participant.name = team_name_clean
    if replace_logo:
        db_participant.logo_url = _normalize_team_logo_url(team_logo_url)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_updated_by_captain',
        payload={
            'team_name': team_name_clean,
            'logo_url': db_participant.logo_url,
            'replace_logo': replace_logo,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def _normalize_team_logo_url(team_logo_url: str | None) -> str | None:
    return team_logo_url.strip() if team_logo_url else None


def _load_managed_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    captain_user_id: UserID,
) -> Result[
    tuple[
        DbNetsessionTourneyTournament,
        Tournament,
        DbNetsessionTourneyParticipant,
    ],
    str,
]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        return Err('Die Teamverwaltung ist gerade nicht verfügbar.')

    db_participant = find_db_managed_team_participant(
        party_id, tournament_id, participant_id, captain_user_id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    return Ok((db_tournament, tournament, db_participant))


def find_managed_team_for_user(
    party_id: PartyID, tournament_id: TournamentID, user_id: UserID
) -> Participant | None:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return None

    return db_participant_to_model(db_participant)


def set_managed_team_ready_state(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    ready: bool,
) -> Result[Participant, str]:
    managed_team_result = _load_managed_team_for_captain(
        party_id, tournament_id, participant_id, initiator.id
    )
    if managed_team_result.is_err():
        return Err(managed_team_result.unwrap_err())
    db_tournament, tournament, db_participant = managed_team_result.unwrap()

    ready_state_error = _check_team_ready_state_change(
        tournament, participant_id, ready=ready
    )
    if ready_state_error is not None:
        return Err(ready_state_error)

    db_participant.status = (
        ParticipantStatus.ready.value
        if ready
        else ParticipantStatus.forming.value
    )

    refresh_match_states_for_participant_readiness(
        db_tournament, participant_id
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_ready_state_set_by_captain',
        payload={'ready': ready},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def find_db_managed_team_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> DbNetsessionTourneyParticipant | None:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=manager_user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
