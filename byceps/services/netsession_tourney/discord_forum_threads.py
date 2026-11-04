"""
byceps.services.netsession_tourney.discord_forum_threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One Discord forum thread per tournament: create, update, recover.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import structlog

from byceps.database import db
from byceps.util.result import Err, Ok

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


def _ensure_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
) -> None:
    _sync_discord_thread_for_tournament(db_tournament, update_existing=False)


def _sync_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    update_existing: bool = True,
) -> None:
    if not db_tournament.discord_enabled or not db_tournament.discord_forum_channel_id:
        return

    match get_configured_discord_bot_credentials():
        case Err(message):
            log.warning(
                'netsession_tourney.discord_forum_thread_credentials_invalid',
                tournament_id=str(db_tournament.id),
                error=message,
            )
            return
        case Ok(None):
            return
        case Ok((application_id, bot_token)):
            pass

    if db_tournament.discord_thread_id:
        try:
            _get_discord_channel(
                application_id=application_id,
                bot_token=bot_token,
                channel_id=db_tournament.discord_thread_id,
            )
        except httpx.HTTPStatusError as exc:
            if _is_discord_resource_missing(exc):
                _clear_discord_thread_reference(
                    db_tournament,
                    audit_action='discord_thread_missing_reset',
                    audit_payload={
                        'thread_id': db_tournament.discord_thread_id,
                        'reason': 'thread_missing',
                    },
                )
            else:
                log.warning(
                    'netsession_tourney.discord_forum_thread_validate_failed',
                    tournament_id=str(db_tournament.id),
                    thread_id=str(db_tournament.discord_thread_id),
                    error=type(exc).__name__,
                )
                return
        except httpx.HTTPError as exc:
            log.warning(
                'netsession_tourney.discord_forum_thread_validate_failed',
                tournament_id=str(db_tournament.id),
                thread_id=str(db_tournament.discord_thread_id),
                error=type(exc).__name__,
            )
            return

    if db_tournament.discord_thread_id:
        if update_existing:
            try:
                _update_discord_forum_thread(
                    db_tournament=db_tournament,
                    application_id=application_id,
                    bot_token=bot_token,
                )
            except httpx.HTTPError as exc:
                log.warning(
                    'netsession_tourney.discord_forum_thread_sync_failed',
                    tournament_id=str(db_tournament.id),
                    thread_id=str(db_tournament.discord_thread_id),
                    error=type(exc).__name__,
                )
        return

    payload = _build_discord_forum_thread_payload(db_tournament)

    try:
        thread_id = _create_discord_forum_thread(
            application_id=application_id,
            bot_token=bot_token,
            forum_channel_id=db_tournament.discord_forum_channel_id,
            payload=payload,
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning(
            'netsession_tourney.discord_forum_thread_create_failed',
            tournament_id=str(db_tournament.id),
            error=type(exc).__name__,
        )
        return

    db_tournament.discord_thread_id = thread_id
    db_tournament.updated_at = datetime.utcnow()
    db.session.commit()

    _append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action='discord_thread_created',
        payload={'thread_id': thread_id},
        created_at=datetime.utcnow(),
    )
    db.session.commit()


def _update_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    application_id: str,
    bot_token: str,
) -> None:
    thread_id = db_tournament.discord_thread_id
    if not thread_id:
        return

    payload = _build_discord_forum_thread_payload(db_tournament)
    channel_payload: dict[str, Any] = {'name': payload['name']}
    if 'applied_tags' in payload:
        channel_payload['applied_tags'] = payload['applied_tags']

    try:
        _patch_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=thread_id,
            payload=channel_payload,
        )
    except httpx.HTTPStatusError as exc:
        if _is_discord_resource_missing(exc):
            _clear_discord_thread_reference(
                db_tournament,
                audit_action='discord_thread_missing_reset',
                audit_payload={
                    'thread_id': thread_id,
                    'reason': 'thread_missing_while_updating',
                },
            )
            _sync_discord_thread_for_tournament(
                db_tournament, update_existing=False
            )
            return
        raise

    try:
        _patch_discord_forum_starter_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=thread_id,
            payload=payload['message'],
        )
    except httpx.HTTPStatusError as exc:
        if not _is_discord_resource_missing(exc):
            raise
    except httpx.HTTPError:
        return


def _recover_deleted_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    failed_thread_id: str,
    exc: httpx.HTTPStatusError,
) -> str | None:
    if not _is_discord_resource_missing(exc):
        return None

    if db_tournament.discord_thread_id == failed_thread_id:
        _clear_discord_thread_reference(
            db_tournament,
            audit_action='discord_thread_missing_reset',
            audit_payload={
                'thread_id': failed_thread_id,
                'reason': 'message_delivery_failed_missing_thread',
            },
        )

    try:
        _sync_discord_thread_for_tournament(
            db_tournament, update_existing=False
        )
    except httpx.HTTPError:
        return None

    return db_tournament.discord_thread_id


def _clear_discord_thread_reference(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    audit_action: str,
    audit_payload: dict[str, Any],
) -> None:
    if not db_tournament.discord_thread_id:
        return

    db_tournament.discord_thread_id = None
    db_tournament.updated_at = datetime.utcnow()
    db.session.commit()

    _append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action=audit_action,
        payload=audit_payload,
        created_at=datetime.utcnow(),
    )
    db.session.commit()
