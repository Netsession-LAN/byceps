"""
byceps.services.netsession_tourney.notification_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notifications of users about tournament events (stored, then sent by browser push and Discord), including manual announcements by admins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from byceps.database import db
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTournament,
)
from .flatout2_races import (
    get_flatout2_round_races,
    get_match_host_participant_id,
    get_selected_host_user_ids,
)
from .models import (
    Stage,
    StageType,
    TournamentID,
    TournamentStatus,
)
from .notification_append import (
    append_notification as append_notification,
)
from .notification_manual import (
    send_manual_tournament_notification as send_manual_tournament_notification,
)
from .notification_recipients import (
    get_active_user_ids_for_tournament,
    get_match_involved_user_ids,
)
from .service_helpers import (
    append_audit_log,
)
from .site_paths import (
    build_site_match_path,
)


def append_notification_for_match_report(
    db_match: DbNetsessionTourneyMatch, stage: Stage, actor_user_id: UserID
) -> None:
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    append_notifications_for_match(
        db_match,
        actor_user_id=actor_user_id,
        kind='result_submitted',
        payload={
            'stage_id': str(stage.id),
            'match_id': str(db_match.id),
            'state': db_match.state,
            'url': (
                build_site_match_path(db_tournament.slug, db_match.id)
                if db_tournament is not None
                else None
            ),
        },
    )


def enqueue_match_ready_notifications(
    db_match: DbNetsessionTourneyMatch,
) -> None:
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    if db_tournament is None:
        return

    if db_tournament.status != TournamentStatus.live.value:
        return

    append_audit_log(
        actor_user_id=None,
        object_type='match',
        object_id=db_match.id,
        action='match_ready',
        payload={'stage_id': str(db_match.stage_id)},
        created_at=datetime.utcnow(),
    )

    append_notifications_for_match(
        db_match,
        actor_user_id=None,
        kind='match_ready',
        payload={
            'match_id': str(db_match.id),
            'stage_id': str(db_match.stage_id),
            'url': build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    enqueue_flatout2_host_assignment_notifications(db_match)


def enqueue_flatout2_host_assignment_notifications(
    db_match: DbNetsessionTourneyMatch,
) -> None:
    payload = _build_flatout2_host_notification_payload(db_match)
    if payload is None:
        return

    recipient_user_ids = get_selected_host_user_ids(db_match)
    if not recipient_user_ids:
        return

    now = datetime.utcnow()
    for user_id in recipient_user_ids:
        append_notification(
            tournament_id=db_match.tournament_id,
            user_id=user_id,
            kind='flatout2_host_assigned',
            payload=payload,
            created_at=now,
        )


def _build_flatout2_host_notification_payload(
    db_match: DbNetsessionTourneyMatch,
) -> dict[str, Any] | None:
    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if (
        db_stage is None
        or db_stage.type != StageType.ffa_flatout2_single_elimination.value
    ):
        return None

    host_participant_id = get_match_host_participant_id(db_match)
    if host_participant_id is None:
        return None

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    if (
        db_tournament is None
        or db_tournament.status != TournamentStatus.live.value
    ):
        return None

    round_races = get_flatout2_round_races(db_match.settings_json or {})

    return {
        'match_id': str(db_match.id),
        'stage_id': str(db_match.stage_id),
        'title': db_tournament.title,
        'round_no': db_match.round_no,
        'url': build_site_match_path(db_tournament.slug, db_match.id),
        'flatout2_round_races': round_races,
    }


def append_notifications_for_match(
    db_match: DbNetsessionTourneyMatch,
    *,
    actor_user_id: UserID | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    recipients = get_match_involved_user_ids(db_match.id)
    if actor_user_id is not None:
        recipients.discard(actor_user_id)

    now = datetime.utcnow()
    for user_id in recipients:
        append_notification(
            tournament_id=db_match.tournament_id,
            user_id=user_id,
            kind=kind,
            payload=payload,
            created_at=now,
        )


def append_notifications_for_tournament(
    tournament_id: TournamentID,
    *,
    actor_user_id: UserID | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    recipients = get_active_user_ids_for_tournament(tournament_id)
    if actor_user_id is not None:
        recipients.discard(actor_user_id)

    now = datetime.utcnow()
    for user_id in recipients:
        append_notification(
            tournament_id=tournament_id,
            user_id=user_id,
            kind=kind,
            payload=payload,
            created_at=now,
        )
