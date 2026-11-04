"""
byceps.services.netsession_tourney.discord_dm_outbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord direct message delivery: processing the outbox, message payloads, test message.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result

from .browser_push_outbox import (
    _build_browser_push_match_label,
    _build_browser_push_message_payload,
)
from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    _decrypt_discord_dm_bot_token,
    _is_missing_discord_dm_table_error,
    DISCORD_DM_MAX_ATTEMPTS,
    DISCORD_DM_TIMEOUT_SECONDS,
)
from .models import (
    DiscordDmOutboxStatus,
)
from .notification_urls import (
    _build_absolute_notification_url,
    _build_browser_push_logo_urls,
)
from .tournament_queries import (
    _build_flatout2_round_race_lines,
)


def process_discord_dm_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmOutbox)
            .filter(
                DbNetsessionTourneyDiscordDmOutbox.status.in_(
                    [
                        DiscordDmOutboxStatus.pending.value,
                        DiscordDmOutboxStatus.failed.value,
                    ]
                )
            )
            .filter(
                (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at.is_(None))
                | (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at <= now)
            )
            .order_by(DbNetsessionTourneyDiscordDmOutbox.created_at.asc())
            .limit(limit)
        ).all()
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return 0
        raise

    processed = 0
    for db_row in db_rows:
        processed += 1
        db_row.attempt_count += 1
        db_row.updated_at = now

        db_notification = db.session.get(
            DbNetsessionTourneyNotification, db_row.notification_id
        )
        if db_notification is None:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Unknown notification.', now
            )
            continue

        db_tournament = db.session.get(
            DbNetsessionTourneyTournament, db_notification.tournament_id
        )
        if db_tournament is None:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Unknown tournament for Discord-DM outbox item.', now
            )
            continue

        db_config = db.session.get(
            DbNetsessionTourneyDiscordDmConfig, db_tournament.party_id
        )
        if (
            db_config is None
            or not db_config.enabled
            or not db_config.application_id
            or not db_config.bot_token_encrypted
        ):
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Discord-DM-Konfiguration ist unvollständig.', now
            )
            continue

        bot_token = _decrypt_discord_dm_bot_token(
            db_config.bot_token_encrypted
        )
        if not bot_token:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Kein gültiges Discord-Bot-Token konfiguriert.', now
            )
            continue

        connected_account = (
            external_accounts_service.find_connected_external_account_for_user_and_service(
                db_notification.user_id, 'discord'
            )
        )
        discord_user_id = (
            connected_account.external_id
            if connected_account is not None
            else None
        )
        if not discord_user_id:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Empfänger hat keinen verbundenen Discord-Account.',
                now,
            )
            continue

        payload = _build_discord_dm_message_payload(
            db_tournament,
            db_notification,
        )

        try:
            _send_discord_dm(
                application_id=db_config.application_id,
                bot_token=bot_token,
                discord_user_id=discord_user_id,
                payload=payload,
            )
        except httpx.HTTPError as exc:
            _schedule_discord_dm_outbox_retry(
                db_row,
                f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            continue
        except ValueError as exc:
            _mark_discord_dm_outbox_dead_letter(db_row, str(exc), now)
            continue

        db_row.status = DiscordDmOutboxStatus.sent.value
        db_row.next_attempt_at = None
        db_row.last_error = None

    db.session.commit()
    return processed


def send_test_discord_dm(
    party_id: PartyID,
    user_id: UserID,
) -> Result[None, str]:
    db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    if db_config is None or not db_config.enabled:
        return Err('Discord-Privatbenachrichtigungen sind nicht aktiviert.')

    if not db_config.application_id or not db_config.bot_token_encrypted:
        return Err('Discord-DM-Konfiguration ist unvollständig.')

    connected_account = (
        external_accounts_service.find_connected_external_account_for_user_and_service(
            user_id, 'discord'
        )
    )
    discord_user_id = (
        connected_account.external_id
        if connected_account is not None
        else None
    )
    if not discord_user_id:
        return Err('Dein Benutzerkonto hat keinen verbundenen Discord-Account.')

    bot_token = _decrypt_discord_dm_bot_token(
        db_config.bot_token_encrypted
    )
    if not bot_token:
        return Err('Kein gültiges Discord-Bot-Token konfiguriert.')

    payload = _build_test_discord_dm_message_payload(party_id)

    try:
        _send_discord_dm(
            application_id=db_config.application_id,
            bot_token=bot_token,
            discord_user_id=discord_user_id,
            payload=payload,
        )
    except httpx.HTTPError as exc:
        return Err(
            f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}'
        )
    except ValueError as exc:
        return Err(str(exc))

    return Ok(None)


def _mark_discord_dm_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordDmOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_dm_outbox_retry(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_DM_MAX_ATTEMPTS:
        _mark_discord_dm_outbox_dead_letter(
            db_row,
            f'Zustellung wiederholt fehlgeschlagen. Letzter Fehler: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordDmOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _build_discord_dm_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    browser_payload = _build_browser_push_message_payload(
        db_tournament, db_notification
    )
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = _build_browser_push_match_label(payload)
    body = str(browser_payload.get('body') or '').strip() or 'Es gibt ein neues Update.'
    url = _build_absolute_notification_url(
        db_tournament.party_id,
        str(browser_payload.get('url') or f'/ns-tourneys/{db_tournament.slug}'),
    )
    icon_url, _image_url = _build_browser_push_logo_urls(db_tournament)
    brand_icon_url = (
        _build_absolute_notification_url(db_tournament.party_id, icon_url)
        if icon_url
        else None
    )
    thumbnail_source_url = db_tournament.logo_url or icon_url
    thumbnail_url = (
        _build_absolute_notification_url(
            db_tournament.party_id, thumbnail_source_url
        )
        if thumbnail_source_url
        else None
    )

    event_meta_by_kind = {
        'tournament_live': {
            'emoji': '🟢',
            'label': 'Turnier live',
            'headline': 'Turnier ist jetzt live',
        },
        'tournament_canceled': {
            'emoji': '⛔',
            'label': 'Turnier abgesagt',
            'headline': 'Turnier wurde abgesagt',
        },
        'match_ready': {
            'emoji': '🎮',
            'label': 'Match spielbereit',
            'headline': 'Match ist spielbereit',
        },
        'flatout2_host_assigned': {
            'emoji': '🏁',
            'label': 'Host ausgewählt',
            'headline': 'Du bist Host für das nächste Rennen',
        },
        'result_submitted': {
            'emoji': '📝',
            'label': 'Ergebnis übermittelt',
            'headline': 'Ergebnis wurde übermittelt',
        },
    }
    event_meta = event_meta_by_kind.get(
        kind,
        {
            'emoji': '🔔',
            'label': 'Benachrichtigung',
            'headline': 'Neues Update',
        },
    )

    description_lines = [f'**{db_tournament.title}**', body]
    fields = [
        {
            'name': 'Ereignis',
            'value': str(event_meta['label'])[:1024],
            'inline': True,
        },
        {
            'name': 'Turnier',
            'value': db_tournament.title[:1024],
            'inline': True,
        },
    ]

    if match_label:
        fields.append(
            {
                'name': 'Spiel',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    if kind == 'flatout2_host_assigned':
        round_no = payload.get('round_no')
        if round_no:
            fields.append(
                {
                    'name': 'Runde',
                    'value': str(round_no)[:1024],
                    'inline': True,
                }
            )
        race_lines = _build_flatout2_round_race_lines(payload)
        if race_lines:
            fields.append(
                {
                    'name': 'Rennen-Setup',
                    'value': '\n'.join(race_lines)[:1024],
                    'inline': False,
                }
            )

    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Direkt zur Seite]({url})',
                'inline': False,
            }
        )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': f"{event_meta['emoji']} {event_meta['headline']}"[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_notification.created_at.replace(microsecond=0).isoformat() + 'Z',
    }

    if url:
        embed['url'] = url

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    if thumbnail_url:
        embed['thumbnail'] = {'url': thumbnail_url}

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _build_test_discord_dm_message_payload(
    party_id: PartyID,
) -> dict[str, Any]:
    url = _build_absolute_notification_url(party_id, '/ns-tourneys/')
    brand_icon_url = _build_absolute_notification_url(
        party_id, '/static_sites/netsession/icon-192.png'
    )

    description_lines = [
        '**Counter-Strike 2 (5on5)**',
        'Upper Bracket • Spiel #2 ist jetzt spielbereit.',
        '',
        'So sehen künftige Turnier- und Match-Benachrichtigungen als Karte aus.',
    ]

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': '🧪 Discord-Testnachricht',
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': [
            {
                'name': 'Ereignis',
                'value': 'Match spielbereit',
                'inline': True,
            },
            {
                'name': 'Turnier',
                'value': 'Counter-Strike 2 (5on5)',
                'inline': True,
            },
            {
                'name': 'Spiel',
                'value': 'WB #2',
                'inline': True,
            },
            {
                'name': 'Status',
                'value': 'Discord-DM-Zustellung aktiv',
                'inline': True,
            },
        ],
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }

    if url:
        embed['url'] = url
        embed['fields'].append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnierübersicht öffnen]({url})',
                'inline': False,
            }
        )

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _send_discord_dm(
    *,
    application_id: str,
    bot_token: str,
    discord_user_id: str,
    payload: dict[str, Any],
) -> None:
    if not application_id.strip():
        raise ValueError('Discord Application ID fehlt.')

    headers = {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }

    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_DM_TIMEOUT_SECONDS,
        headers=headers,
    ) as client:
        dm_response = client.post(
            '/users/@me/channels',
            json={'recipient_id': discord_user_id},
        )
        dm_response.raise_for_status()
        channel_id = str(dm_response.json().get('id') or '').strip()
        if not channel_id:
            raise ValueError('Discord-DM-Kanal konnte nicht erstellt werden.')

        message_response = client.post(
            f'/channels/{channel_id}/messages',
            json=payload,
        )
        message_response.raise_for_status()
