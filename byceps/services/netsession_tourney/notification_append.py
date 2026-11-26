"""
byceps.services.netsession_tourney.notification_append
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Appending a notification and queueing its browser push and Discord DM delivery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.user.models import UserID
from byceps.util.uuid import generate_uuid7

from .browser_push_service import (
    BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
)
from .models import (
    BrowserPushOutboxID,
    DiscordDmOutboxID,
    TournamentID,
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
    if db_tournament is None:
        return

    if _should_queue_browser_push_notification(db_tournament, kind, user_id):
        db.session.add(
            DbNetsessionTourneyBrowserPushOutbox(
                BrowserPushOutboxID(generate_uuid7()),
                db_notification.id,
                created_at,
            )
        )

    if _should_queue_discord_dm_notification(db_tournament, kind, user_id):
        _queue_discord_dm_notification_for_connected_account(
            user_id, db_notification.id, created_at
        )


def _should_queue_browser_push_notification(
    db_tournament: DbNetsessionTourneyTournament, kind: str, user_id: UserID
) -> bool:
    return (
        kind in BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS
        and is_browser_push_enabled_for_party(db_tournament.party_id)
        and has_active_browser_push_subscription_for_user(
            db_tournament.party_id, user_id
        )
    )


def _should_queue_discord_dm_notification(
    db_tournament: DbNetsessionTourneyTournament, kind: str, user_id: UserID
) -> bool:
    return bool(
        kind in DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        and is_discord_dm_enabled_for_party(db_tournament.party_id)
        and db_tournament.discord_dm_enabled
        and kind in (db_tournament.discord_dm_event_mask or [])
        and has_active_discord_dm_subscription_for_user(
            db_tournament.party_id, user_id
        )
    )


def _queue_discord_dm_notification_for_connected_account(
    user_id: UserID, notification_id: Any, created_at: datetime
) -> None:
    connected_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        user_id, 'discord'
    )
    if connected_account is not None and connected_account.external_id:
        db.session.add(
            DbNetsessionTourneyDiscordDmOutbox(
                DiscordDmOutboxID(generate_uuid7()),
                notification_id,
                created_at,
            )
        )
