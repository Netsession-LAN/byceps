"""
byceps.services.netsession_tourney.notification_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notifications of users about tournament events (stored, then sent by browser push and Discord), including manual announcements by admins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .browser_push_service import (
    get_active_browser_push_subscription_recipients_for_tournament,
    BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
)
from .discord_service import (
    enqueue_discord_event,
)
from .models import (
    BrowserPushOutboxID,
    DiscordDmOutboxID,
    Stage,
    StageType,
    TournamentID,
    TournamentStatus,
)
from .service_helpers import (
    append_audit_log,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)
from .flatout2_races import (
    get_flatout2_round_races,
    get_match_host_participant_id,
    get_selected_host_user_ids,
)
from .notification_recipients import (
    get_active_user_ids_for_tournament,
    get_match_involved_user_ids,
)
from .site_paths import (
    build_site_match_path,
    build_site_tournament_overview_path,
)


@dataclass(frozen=True, kw_only=True)
class ManualNotificationDispatchResult:
    recipient_user_count: int
    subscription_count: int


def send_manual_tournament_notification(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    title: str,
    body: str,
    target_url: str | None = None,
) -> Result[ManualNotificationDispatchResult, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')
    if not is_browser_push_enabled_for_party(party_id):
        return Err('Browser-Benachrichtigungen sind ausgeschaltet.')

    title = title.strip()
    body = body.strip()
    target_url = (target_url or '').strip() or None

    error = _validate_manual_notification_input(title, body, target_url)
    if error is not None:
        return Err(error)

    recipients, subscription_count = (
        get_active_browser_push_subscription_recipients_for_tournament(
            party_id, tournament_id
        )
    )

    now = datetime.utcnow()
    _append_manual_announcement_notifications(
        tournament_id,
        recipients,
        title=title,
        body=body,
        url=target_url
        or build_site_tournament_overview_path(db_tournament.slug),
        created_at=now,
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='manual_notification_sent',
        payload={
            'title': title,
            'body': body,
            'target_url': target_url,
            'recipient_user_count': len(recipients),
            'subscription_count': subscription_count,
        },
        created_at=now,
    )

    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='manual_announcement',
        payload={
            'title': title,
            'body': body,
            'url': target_url
            or build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    db.session.commit()
    return Ok(
        ManualNotificationDispatchResult(
            recipient_user_count=len(recipients),
            subscription_count=subscription_count,
        )
    )


def _validate_manual_notification_input(
    title: str, body: str, target_url: str | None
) -> str | None:
    """Return the first validation error message, or `None` if valid."""
    if not title:
        return 'Bitte einen Titel angeben.'
    if not body:
        return 'Bitte eine Nachricht angeben.'
    if target_url is not None and not target_url.startswith('/'):
        return 'Die Ziel-Adresse muss relativ sein und mit / beginnen.'
    return None


def _append_manual_announcement_notifications(
    tournament_id: TournamentID,
    recipients: set[UserID],
    *,
    title: str,
    body: str,
    url: str,
    created_at: datetime,
) -> None:
    for user_id in recipients:
        append_notification(
            tournament_id=tournament_id,
            user_id=user_id,
            kind='manual_announcement',
            payload={
                'title': title,
                'body': body,
                'url': url,
            },
            created_at=created_at,
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
                build_site_match_path(
                    db_tournament.slug, db_match.id
                )
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
    if db_stage is None or db_stage.type != StageType.ffa_flatout2_single_elimination.value:
        return None

    host_participant_id = get_match_host_participant_id(db_match)
    if host_participant_id is None:
        return None

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    if db_tournament is None or db_tournament.status != TournamentStatus.live.value:
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


def append_notification(
    *,
    tournament_id: TournamentID,
    user_id: UserID,
    kind: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> None:
    db_notification = DbNetsessionTourneyNotification(
        generate_uuid7(),
        tournament_id,
        user_id,
        kind,
        payload,
        created_at,
    )
    db.session.add(db_notification)

    db_tournament = db.session.get(DbNetsessionTourneyTournament, tournament_id)
    if (
        db_tournament is not None
        and kind in BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS
        and is_browser_push_enabled_for_party(db_tournament.party_id)
        and has_active_browser_push_subscription_for_user(
            db_tournament.party_id, user_id
        )
    ):
        db.session.add(
            DbNetsessionTourneyBrowserPushOutbox(
                BrowserPushOutboxID(generate_uuid7()),
                db_notification.id,
                created_at,
            )
        )

    if (
        db_tournament is not None
        and kind in DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        and is_discord_dm_enabled_for_party(db_tournament.party_id)
        and db_tournament.discord_dm_enabled
        and kind in (db_tournament.discord_dm_event_mask or [])
        and has_active_discord_dm_subscription_for_user(
            db_tournament.party_id, user_id
        )
    ):
        connected_account = (
            external_accounts_service.find_connected_external_account_for_user_and_service(
                user_id, 'discord'
            )
        )
        if connected_account is not None and connected_account.external_id:
            db.session.add(
                DbNetsessionTourneyDiscordDmOutbox(
                    DiscordDmOutboxID(generate_uuid7()),
                    db_notification.id,
                    created_at,
                )
            )
