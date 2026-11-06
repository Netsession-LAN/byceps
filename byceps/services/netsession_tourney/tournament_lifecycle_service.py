"""
byceps.services.netsession_tourney.tournament_lifecycle_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lifecycle of a tournament: publish, back to draft, close, cancel, delete.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .coin_cancel_refunds import refund_all_coins_of_canceled_tournament
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournamentAdmin,
    DbNetsessionTourneyTournamentPrize,
)
from .discord_forum_threads import (
    sync_discord_thread_for_tournament,
)
from .discord_payloads import (
    build_discord_tournament_finished_payload,
)
from .discord_service import (
    enqueue_discord_event,
)
from .models import (
    StageStatus,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    append_notifications_for_tournament,
    enqueue_match_ready_notifications,
)
from .registration_validation import (
    validate_bracket_ready_team_sizes,
)
from .service_helpers import (
    append_audit_log,
    db_tournament_to_model,
)
from .stage_activation import (
    activate_prepared_matches_for_live_tournament,
    activate_prepared_stages_for_live_tournament,
    delete_stage_matches,
    demote_prepared_matches_for_draft_tournament,
)
from .tournament_closing import validate_can_close
from .tournament_queries import (
    build_site_tournament_overview_path,
    find_db_tournament_for_party,
    get_participants_for_tournament,
    get_stages_for_tournament,
)


def publish_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    stages = get_stages_for_tournament(party_id, tournament_id)
    participants = get_participants_for_tournament(party_id, tournament_id)
    team_size_validation_result = validate_bracket_ready_team_sizes(
        tournament, participants
    )
    if team_size_validation_result.is_err():
        return Err(team_size_validation_result.unwrap_err())

    validation_result = domain_service.validate_publishable(
        tournament, stages, participants
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    db_tournament.status = TournamentStatus.live.value
    db_tournament.updated_at = datetime.utcnow()

    activate_prepared_stages_for_live_tournament(tournament_id, stages)
    db_ready_matches = activate_prepared_matches_for_live_tournament(
        tournament_id
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_published',
        payload={},
        created_at=datetime.utcnow(),
    )
    append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_live',
        payload={
            'slug': db_tournament.slug,
            'url': build_site_tournament_overview_path(db_tournament.slug),
        },
    )
    for db_match in db_ready_matches:
        enqueue_match_ready_notifications(db_match)

    db.session.commit()

    sync_discord_thread_for_tournament(db_tournament)

    return Ok(db_tournament_to_model(db_tournament))


def close_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if (close_check := validate_can_close(db_tournament)).is_err():
        return close_check

    db_tournament.status = TournamentStatus.closed.value
    db_tournament.updated_at = datetime.utcnow()

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_closed',
        payload={},
        created_at=datetime.utcnow(),
    )
    append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_closed',
        payload={
            'slug': db_tournament.slug,
            'url': build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='tournament_finished',
        payload=build_discord_tournament_finished_payload(db_tournament),
    )
    db.session.commit()
    return Ok(db_tournament_to_model(db_tournament))


def cancel_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status == TournamentStatus.closed.value:
        return Err('Abgeschlossene Turniere können nicht abgesagt werden.')

    if db_tournament.status == TournamentStatus.canceled.value:
        return Err('Das Turnier ist bereits abgesagt.')

    db_tournament.status = TournamentStatus.canceled.value
    db_tournament.registration_open = False
    db_tournament.updated_at = datetime.utcnow()
    refund_all_coins_of_canceled_tournament(
        party_id, db_tournament_to_model(db_tournament), initiator.id
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_canceled',
        payload={},
        created_at=datetime.utcnow(),
    )
    append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_canceled',
        payload={
            'slug': db_tournament.slug,
            'url': build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='tournament_canceled',
        payload={'slug': db_tournament.slug},
    )
    db.session.commit()

    return Ok(db_tournament_to_model(db_tournament))


def unpublish_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.live.value:
        return Err('Nur laufende Turniere können zurück in den Entwurf.')

    has_reported_results = (
        db.session.scalar(
            select(
                select(DbNetsessionTourneyMatchResult.id)
                .join(
                    DbNetsessionTourneyMatch,
                    DbNetsessionTourneyMatchResult.match_id
                    == DbNetsessionTourneyMatch.id,
                )
                .filter(DbNetsessionTourneyMatch.tournament_id == tournament_id)
                .filter(
                    DbNetsessionTourneyMatchResult.submitted_by_user_id.is_not(
                        None
                    )
                )
                .exists()
            )
        )
        or False
    )
    if has_reported_results:
        return Err(
            'Nachdem Ergebnisse gemeldet wurden, kann das Turnier nicht mehr zurück in den Entwurf.'
        )

    db_tournament.status = TournamentStatus.draft.value
    db_tournament.updated_at = datetime.utcnow()

    db_live_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.status == StageStatus.live.value)
    ).all()
    for db_stage in db_live_stages:
        db_stage.status = StageStatus.draft.value

    demote_prepared_matches_for_draft_tournament(tournament_id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_unpublished',
        payload={'live_stage_count': len(db_live_stages)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(db_tournament_to_model(db_tournament))


def delete_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status not in {
        TournamentStatus.draft.value,
        TournamentStatus.canceled.value,
    }:
        return Err(
            'Nur Entwürfe und abgesagte Turniere können gelöscht werden. '
            'Sage das Turnier zuerst ab.'
        )

    # Order matters because of foreign keys.
    _delete_stages_with_matches(tournament_id)
    _delete_participants_and_registrations(tournament_id)
    _delete_notifications_and_outboxes(tournament_id)
    _delete_admins_and_prizes(tournament_id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_deleted',
        payload={'slug': db_tournament.slug, 'title': db_tournament.title},
        created_at=datetime.utcnow(),
    )

    db.session.delete(db_tournament)
    db.session.commit()

    return Ok(None)


def _delete_stages_with_matches(tournament_id: TournamentID) -> None:
    stage_ids = db.session.scalars(
        select(DbNetsessionTourneyStage.id).filter_by(tournament_id=tournament_id)
    ).all()
    for stage_id in stage_ids:
        delete_stage_matches(stage_id)

    db.session.execute(
        delete(DbNetsessionTourneyStage).filter_by(tournament_id=tournament_id)
    )


def _delete_participants_and_registrations(tournament_id: TournamentID) -> None:
    participant_ids = db.session.scalars(
        select(DbNetsessionTourneyParticipant.id).filter_by(
            tournament_id=tournament_id
        )
    ).all()
    if participant_ids:
        db.session.execute(
            delete(DbNetsessionTourneyTeamMember).filter(
                DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
            )
        )

    db.session.execute(
        delete(DbNetsessionTourneyParticipant).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id
        )
    )


def _delete_notifications_and_outboxes(tournament_id: TournamentID) -> None:
    # Delete rows referencing the tournament or its notifications explicitly,
    # independent of whether the database has `ON DELETE CASCADE` on those
    # foreign keys (tables created from the models did not).
    notification_ids = select(DbNetsessionTourneyNotification.id).filter_by(
        tournament_id=tournament_id
    )
    db.session.execute(
        delete(DbNetsessionTourneyBrowserPushOutbox).filter(
            DbNetsessionTourneyBrowserPushOutbox.notification_id.in_(
                notification_ids
            )
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyDiscordDmOutbox).filter(
            DbNetsessionTourneyDiscordDmOutbox.notification_id.in_(
                notification_ids
            )
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyNotification).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyDiscordOutbox).filter_by(
            tournament_id=tournament_id
        )
    )


def _delete_admins_and_prizes(tournament_id: TournamentID) -> None:
    db.session.execute(
        delete(DbNetsessionTourneyTournamentAdmin).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyTournamentPrize).filter_by(
            tournament_id=tournament_id
        )
    )
