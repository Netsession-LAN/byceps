"""
byceps.services.netsession_tourney.notification_manual
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Manual tournament notifications sent by an admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result

from .browser_push_service import (
    get_active_browser_push_subscription_recipients_for_tournament,
    is_browser_push_enabled_for_party,
)
from .discord_service import (
    enqueue_discord_event,
)
from .models import (
    TournamentID,
)
from .notification_append import (
    append_notification,
)
from .service_helpers import (
    append_audit_log,
)
from .site_paths import (
    build_site_tournament_overview_path,
)
from .tournament_queries import (
    find_db_tournament_for_party,
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
    target_url = _normalize_manual_notification_target_url(target_url)

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
        url=_resolve_manual_notification_url(target_url, db_tournament.slug),
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
            'url': _resolve_manual_notification_url(
                target_url, db_tournament.slug
            ),
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


def _normalize_manual_notification_target_url(
    target_url: str | None,
) -> str | None:
    return (target_url or '').strip() or None


def _resolve_manual_notification_url(
    target_url: str | None, tournament_slug: str
) -> str:
    return target_url or build_site_tournament_overview_path(tournament_slug)
