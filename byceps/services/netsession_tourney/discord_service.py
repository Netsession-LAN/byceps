"""
byceps.services.netsession_tourney.discord_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord forum integration: configuration, event queue and its processing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .browser_push_outbox import (  # noqa: F401
    _build_browser_push_match_label,
    _build_browser_push_message_payload,
    _build_browser_push_private_key_for_pywebpush,
    _build_browser_push_vapid_subject,
    _format_browser_push_delivery_error,
    _get_browser_push_endpoint_host,
    _mark_browser_push_outbox_dead_letter,
    _schedule_browser_push_outbox_retry,
    process_browser_push_outbox,
)
from .browser_push_service import (  # noqa: F401
    _build_default_browser_push_config,
    _decrypt_browser_push_private_key,
    _derive_browser_push_public_key,
    _encrypt_browser_push_private_key,
    _generate_browser_push_private_key_pem,
    _get_active_browser_push_subscription_recipients_for_tournament,
    _get_browser_push_fernet,
    _get_browser_push_serializer,
    _is_missing_browser_push_table_error,
    BROWSER_PUSH_MAX_ATTEMPTS,
    BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS,
    configure_browser_push,
    count_active_browser_push_subscriptions_for_user,
    count_browser_push_subscribed_participants_for_tournament,
    disable_browser_push_subscription,
    get_browser_push_config,
    get_browser_push_public_key_for_party,
    get_browser_push_subscribed_user_ids_for_tournament,
    get_recent_browser_push_outbox_entries_for_tournament,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
    upsert_browser_push_subscription,
)
from .coin_service import (  # noqa: F401
    _append_coin_ledger_entry,
    _build_default_coin_settings,
    _charge_coins_for_tournament_registration,
    _get_manual_coin_adjustment_amount_for_user,
    _get_registration_coin_delta_amount_for_user,
    _get_ticket_coin_amount_for_user,
    _refund_coins_for_tournament_registration_if_available,
    _validate_coin_cost,
    adjust_user_coins,
    configure_coin_settings,
    get_coin_settings,
    get_recent_coin_ledger_entries_for_user,
    get_ticket_category_coin_settings_for_party,
    get_user_coin_balance,
    get_user_coin_balances,
    is_tournament_coin_refund_available,
)
from .dbmodels import (
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (  # noqa: F401
    _build_default_discord_dm_config,
    _decrypt_discord_dm_bot_token,
    _encrypt_discord_dm_bot_token,
    _get_discord_dm_fernet,
    _is_missing_discord_dm_table_error,
    _mask_discord_dm_bot_token,
    configure_discord_dm,
    count_active_discord_dm_subscriptions_for_user,
    disable_discord_dm_subscription,
    DISCORD_DM_MAX_ATTEMPTS,
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    DISCORD_DM_TIMEOUT_SECONDS,
    get_configured_discord_bot_credentials,
    get_discord_dm_config,
    get_enabled_discord_dm_bot_credentials,
    get_masked_discord_dm_bot_token,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
    upsert_discord_dm_subscription,
)
from .discord_forum_api import (  # noqa: F401
    _build_discord_bot_headers,
    _create_discord_forum_thread,
    _get_discord_channel,
    _is_discord_resource_missing,
    _patch_discord_channel,
    _patch_discord_forum_starter_message,
    _post_discord_forum_message,
    DISCORD_FORUM_TIMEOUT_SECONDS,
)
from .discord_forum_threads import (  # noqa: F401
    _clear_discord_thread_reference,
    _ensure_discord_thread_for_tournament,
    _recover_deleted_discord_forum_thread,
    _sync_discord_thread_for_tournament,
    _update_discord_forum_thread,
)
from .discord_payloads import (  # noqa: F401
    _build_discord_forum_thread_payload,
    _build_discord_match_completed_payload,
    _build_discord_message_payload,
    _build_discord_tournament_finished_payload,
)
from .discord_result_summaries import (  # noqa: F401
    _build_discord_match_completed_description,
    _build_discord_match_completed_fields,
    _build_discord_match_result_summary,
    _build_discord_tournament_finished_description,
    _build_discord_tournament_finished_fields,
    _build_discord_tournament_result_summary,
    _format_discord_tournament_placement,
    _normalize_discord_tournament_placements,
)
from .models import (
    DiscordOutboxID,
    DiscordOutboxStatus,
    Tournament,
    TournamentID,
)
from .notification_labels import (  # noqa: F401
    _build_double_elimination_notification_match_label,
    _build_double_elimination_notification_match_labels,
    _is_loser_notification_outcome,
    _label_notification_bracket_matches,
)
from .notification_urls import (  # noqa: F401
    _build_absolute_notification_url,
    _build_browser_push_badge_url,
    _build_browser_push_logo_urls,
    _find_browser_push_site_server_name,
    _to_browser_push_asset_url,
)
from .ranking_order import (  # noqa: F401
    _build_swiss_head_to_head_scores,
    _sort_ranked_participant_ids,
)
from .service_helpers import (  # noqa: F401
    _append_audit_log,
    _db_browser_push_config_to_model,
    _db_coin_ledger_entry_to_model,
    _db_coin_settings_to_model,
    _db_discord_dm_config_to_model,
    _db_match_chat_message_to_model,
    _db_match_result_to_model,
    _db_match_slot_to_model,
    _db_match_to_model,
    _db_participant_to_model,
    _db_registration_to_model,
    _db_stage_to_model,
    _db_team_member_to_model,
    _db_ticket_category_coin_settings_to_model,
    _db_tournament_category_to_model,
    _db_tournament_prize_to_model,
    _db_tournament_rule_template_to_model,
    _db_tournament_to_model,
    _find_sponsor_logo_target_url,
    _parse_source_outcome,
)
from .stage_ranking import (  # noqa: F401
    _build_stage_ranking_data,
    _get_ranked_participant_ids_for_stage,
    _StageRankingData,
)
from .tournament_category_service import (  # noqa: F401
    _ensure_default_tournament_category_for_party,
    _find_db_tournament_category,
    _resolve_tournament_category_id_for_party,
    create_tournament_category,
    DEFAULT_TOURNAMENT_CATEGORY_TITLE,
    find_tournament_category,
    get_tournament_categories_for_party,
    move_tournament_category_down,
    move_tournament_category_up,
    update_tournament_category,
)
from .tournament_prize_service import (  # noqa: F401
    _find_db_tournament_prize,
    create_tournament_prize,
    delete_tournament_prize,
    find_tournament_prize,
    get_tournament_prizes_for_tournament,
    update_tournament_prize,
)
from .tournament_queries import (  # noqa: F401
    _build_flatout2_first_race_summary,
    _build_flatout2_round_race_lines,
    _build_site_match_path,
    _build_site_tournament_overview_path,
    _db_stage_to_model_with_effective_status,
    _find_db_tournament_for_party,
    _get_active_user_ids_for_tournament,
    _get_ffa_points_per_kill,
    _get_flatout2_round_races,
    _get_match_host_participant_id,
    _get_match_involved_user_ids,
    _get_selected_host_user_ids,
    _is_walkover_score_json,
    _parse_match_result_slot_scores,
    _parse_numeric_score_value,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from .tournament_rule_template_service import (  # noqa: F401
    _find_db_tournament_rule_template,
    create_tournament_rule_template,
    find_tournament_rule_template,
    find_tournament_rule_template_by_slug_for_party,
    get_tournament_rule_templates_for_party,
    update_tournament_rule_template,
)


log = structlog.get_logger()


DISCORD_SUPPORTED_EVENTS = {
    'manual_announcement',
    'match_completed',
    'stage_started',
    'tournament_canceled',
    'tournament_finished',
    'tournament_live',
}


DISCORD_MAX_ATTEMPTS = 5


def enqueue_discord_event(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    if event_name not in DISCORD_SUPPORTED_EVENTS:
        log.warning(
            'netsession_tourney.discord_event_ignored_unknown',
            tournament_id=str(tournament_id),
            event_name=event_name,
        )
        return

    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None or not db_tournament.discord_enabled:
        return

    if event_name not in (db_tournament.discord_event_mask or []):
        return

    db.session.add(
        DbNetsessionTourneyDiscordOutbox(
            DiscordOutboxID(generate_uuid7()),
            tournament_id,
            event_name,
            payload,
            datetime.utcnow(),
        )
    )
    db.session.commit()


def process_discord_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyDiscordOutbox)
        .filter(
            DbNetsessionTourneyDiscordOutbox.status.in_(
                [
                    DiscordOutboxStatus.pending.value,
                    DiscordOutboxStatus.failed.value,
                ]
            )
        )
        .filter(
            (DbNetsessionTourneyDiscordOutbox.next_attempt_at.is_(None))
            | (DbNetsessionTourneyDiscordOutbox.next_attempt_at <= now)
        )
        .order_by(DbNetsessionTourneyDiscordOutbox.created_at.asc())
        .limit(limit)
    ).all()

    match get_configured_discord_bot_credentials():
        case Err(message):
            credentials_error = message
            credentials = None
        case Ok(credentials):
            credentials_error = None

    processed = 0
    for db_row in db_rows:
        processed += 1
        db_row.attempt_count += 1
        db_row.updated_at = now

        db_tournament = db.session.get(
            DbNetsessionTourneyTournament, db_row.tournament_id
        )
        if db_tournament is None:
            _mark_discord_outbox_dead_letter(
                db_row, 'Unknown tournament for Discord outbox item.', now
            )
            continue

        if not db_tournament.discord_enabled:
            _mark_discord_outbox_dead_letter(
                db_row,
                'Discord-Forum ist für dieses Turnier nicht aktiviert.',
                now,
            )
            continue

        if not db_tournament.discord_forum_channel_id:
            _mark_discord_outbox_dead_letter(
                db_row,
                'Keine Discord-Forum-Channel-ID konfiguriert.',
                now,
            )
            continue

        if credentials is None:
            _schedule_discord_outbox_retry(
                db_row,
                credentials_error
                or 'Keine gültige Discord-Bot-Konfiguration aktiv.',
                now,
            )
            continue

        application_id, bot_token = credentials
        if not db_tournament.discord_thread_id:
            try:
                _sync_discord_thread_for_tournament(db_tournament)
            except Exception:
                pass

        thread_id = db_tournament.discord_thread_id
        if not thread_id:
            _schedule_discord_outbox_retry(
                db_row,
                'Discord-Forum-Thread konnte noch nicht erstellt werden.',
                now,
            )
            continue

        try:
            _post_discord_forum_message(
                application_id=application_id,
                bot_token=bot_token,
                thread_id=thread_id,
                payload=_build_discord_message_payload(
                    db_tournament, db_row
                ),
            )
        except httpx.HTTPStatusError as exc:
            recovered_thread_id = _recover_deleted_discord_forum_thread(
                db_tournament=db_tournament,
                failed_thread_id=thread_id,
                exc=exc,
            )
            if recovered_thread_id:
                try:
                    _post_discord_forum_message(
                        application_id=application_id,
                        bot_token=bot_token,
                        thread_id=recovered_thread_id,
                        payload=_build_discord_message_payload(
                            db_tournament, db_row
                        ),
                    )
                except httpx.HTTPError as retry_exc:
                    _schedule_discord_outbox_retry(
                        db_row,
                        (
                            'Discord-Forum-Anfrage fehlgeschlagen: '
                            f'{type(retry_exc).__name__}'
                        ),
                        now,
                    )
                    log.warning(
                        'netsession_tourney.discord_forum_delivery_failed',
                        tournament_id=str(db_row.tournament_id),
                        outbox_id=str(db_row.id),
                        event_name=db_row.event_name,
                        error=type(retry_exc).__name__,
                    )
                    continue

                db_row.status = DiscordOutboxStatus.sent.value
                db_row.next_attempt_at = None
                db_row.last_error = None
                continue

            _schedule_discord_outbox_retry(
                db_row,
                f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            log.warning(
                'netsession_tourney.discord_forum_delivery_failed',
                tournament_id=str(db_row.tournament_id),
                outbox_id=str(db_row.id),
                event_name=db_row.event_name,
                error=type(exc).__name__,
            )
            continue
        except httpx.HTTPError as exc:
            _schedule_discord_outbox_retry(
                db_row,
                f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            log.warning(
                'netsession_tourney.discord_forum_delivery_failed',
                tournament_id=str(db_row.tournament_id),
                outbox_id=str(db_row.id),
                event_name=db_row.event_name,
                error=type(exc).__name__,
            )
            continue

        db_row.status = DiscordOutboxStatus.sent.value
        db_row.next_attempt_at = None
        db_row.last_error = None
    db.session.commit()
    return processed


def configure_discord(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    enabled: bool,
    forum_channel_id: str | None,
    discord_forum_image_url: str | None,
    applied_tag_ids: list[str],
    event_mask: list[str],
    discord_dm_enabled: bool,
    discord_dm_event_mask: list[str],
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_forum_channel_id = (forum_channel_id or '').strip() or None
    normalized_discord_forum_image_url = (
        discord_forum_image_url.strip() if discord_forum_image_url else None
    )
    normalized_event_mask = sorted(set(event_mask))
    if enabled and not normalized_forum_channel_id:
        return Err('Eine Discord-Forum-Channel-ID ist erforderlich.')

    invalid_events = sorted(
        set(normalized_event_mask).difference(DISCORD_SUPPORTED_EVENTS)
    )
    if invalid_events:
        return Err(
            'Unbekannte Discord-Forum-Events: ' + ', '.join(invalid_events)
        )
    if enabled and not normalized_event_mask:
        return Err(
            'Mindestens ein Discord-Forum-Event muss ausgewählt werden.'
        )

    invalid_dm_events = sorted(
        set(discord_dm_event_mask).difference(DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS)
    )
    if invalid_dm_events:
        return Err(
            'Unbekannte Discord-DM-Ereignisse: ' + ', '.join(invalid_dm_events)
        )

    normalized_discord_dm_event_mask = sorted(set(discord_dm_event_mask))
    if discord_dm_enabled and not normalized_discord_dm_event_mask:
        return Err(
            'Mindestens ein Discord-DM-Event muss ausgewählt werden.'
        )

    forum_channel_changed = (
        db_tournament.discord_forum_channel_id != normalized_forum_channel_id
    )
    db_tournament.discord_enabled = enabled
    db_tournament.discord_forum_channel_id = normalized_forum_channel_id
    db_tournament.discord_forum_image_url = normalized_discord_forum_image_url
    if forum_channel_changed:
        db_tournament.discord_thread_id = None
    db_tournament.discord_applied_tag_ids = list(applied_tag_ids)
    db_tournament.discord_event_mask = normalized_event_mask
    db_tournament.discord_dm_enabled = discord_dm_enabled
    db_tournament.discord_dm_event_mask = normalized_discord_dm_event_mask
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='discord_configuration_updated',
        payload={
            'enabled': enabled,
            'forum_channel_id': normalized_forum_channel_id,
            'discord_forum_image_url': normalized_discord_forum_image_url,
            'event_mask': normalized_event_mask,
            'discord_dm_enabled': discord_dm_enabled,
            'discord_dm_event_mask': normalized_discord_dm_event_mask,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    if db_tournament.discord_enabled:
        _sync_discord_thread_for_tournament(db_tournament)

    return Ok(_db_tournament_to_model(db_tournament))


def _mark_discord_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_outbox_retry(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_MAX_ATTEMPTS:
        _mark_discord_outbox_dead_letter(
            db_row,
            f'Delivery failed repeatedly. Last error: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now
