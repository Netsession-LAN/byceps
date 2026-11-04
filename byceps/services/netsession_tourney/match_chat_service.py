"""
byceps.services.netsession_tourney.match_chat_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Chat of the participants of a match.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchChatMessage,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournament,
)
from .models import (
    MatchChatMessage,
    MatchID,
    TournamentID,
)
from .notification_service import (
    _append_notifications_for_match,
)
from .service_helpers import (
    _append_audit_log,
    _db_match_chat_message_to_model,
)
from .tournament_queries import (
    _build_site_match_path,
    _find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
)


def can_user_access_match_chat(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    user_id: UserID,
    *,
    is_admin_or_referee: bool = False,
) -> bool:
    if is_admin_or_referee:
        return True

    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return False

    match_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            id=match_id,
            tournament_id=tournament_id,
        )
    )
    if not match_exists:
        return False

    match_participant_ids = {
        participant_id
        for participant_id in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot.participant_id).filter_by(
                match_id=match_id
            )
        ).all()
        if participant_id is not None
    }
    if not match_participant_ids:
        return False

    own_participant_ids = set(
        db.session.scalars(
            select(DbNetsessionTourneyParticipant.id)
            .filter_by(tournament_id=tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
            .filter(
                or_(
                    DbNetsessionTourneyParticipant.user_id == user_id,
                    DbNetsessionTourneyParticipant.manager_user_id == user_id,
                )
            )
        ).all()
    )

    team_participant_ids = set(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.participant_id)
            .join(
                DbNetsessionTourneyParticipant,
                DbNetsessionTourneyParticipant.id
                == DbNetsessionTourneyTeamMember.participant_id,
            )
            .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
            .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        ).all()
    )

    return bool((own_participant_ids | team_participant_ids) & match_participant_ids)


def get_match_chat_messages(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
) -> list[MatchChatMessage]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    db_messages = db.session.scalars(
        select(DbNetsessionTourneyMatchChatMessage)
        .filter_by(
            tournament_id=tournament_id,
            match_id=match_id,
        )
        .order_by(DbNetsessionTourneyMatchChatMessage.created_at.asc())
    ).all()
    return [_db_match_chat_message_to_model(item) for item in db_messages]


def post_match_chat_message(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    actor_user_id: UserID,
    body: str,
    *,
    actor_is_admin_or_referee: bool = False,
) -> Result[MatchChatMessage, str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    if not can_user_access_match_chat(
        party_id,
        tournament_id,
        match_id,
        actor_user_id,
        is_admin_or_referee=actor_is_admin_or_referee,
    ):
        return Err('Du darfst in diesem Match-Chat nicht schreiben.')

    body = body.strip()
    if not body:
        return Err('Die Nachricht darf nicht leer sein.')
    if len(body) > 2000:
        return Err('Die Nachricht ist zu lang.')

    now = datetime.utcnow()
    db_message = DbNetsessionTourneyMatchChatMessage(
        generate_uuid7(),
        tournament_id,
        match_id,
        actor_user_id,
        body,
        now,
    )
    db.session.add(db_message)

    db_tournament = db.session.get(DbNetsessionTourneyTournament, tournament_id)

    _append_audit_log(
        actor_user_id=actor_user_id,
        object_type='match',
        object_id=match_id,
        action='chat_message_posted',
        payload={'body_preview': body[:120]},
        created_at=now,
    )
    _append_notifications_for_match(
        db_match,
        actor_user_id=actor_user_id,
        kind='chat_message_posted',
        payload={
            'match_id': str(match_id),
            'body_preview': body[:120],
            'url': (
                _build_site_match_path(db_tournament.slug, match_id)
                if db_tournament is not None
                else None
            ),
        },
    )

    db.session.commit()
    return Ok(_db_match_chat_message_to_model(db_message))
