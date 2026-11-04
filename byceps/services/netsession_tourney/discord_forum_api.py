"""
byceps.services.netsession_tourney.discord_forum_api
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calls to the Discord API for forum threads (create, read, update, post).
"""

from __future__ import annotations

from typing import Any

import httpx

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


DISCORD_FORUM_TIMEOUT_SECONDS = 10


def _is_discord_resource_missing(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 404


def _build_discord_bot_headers(
    *, application_id: str, bot_token: str
) -> dict[str, str]:
    return {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }


def _create_discord_forum_thread(
    *,
    application_id: str,
    bot_token: str,
    forum_channel_id: str,
    payload: dict[str, Any],
) -> str:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{forum_channel_id}/threads',
            json=payload,
        )
        response.raise_for_status()
        response_data = response.json()
        thread_id = str(response_data.get('id') or '').strip()
        if not thread_id:
            raise ValueError('Discord-Forum-Thread konnte nicht erstellt werden.')
        return thread_id


def _get_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
) -> dict[str, Any]:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.get(f'/channels/{channel_id}')
        response.raise_for_status()
        return response.json()


def _patch_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(f'/channels/{channel_id}', json=payload)
        response.raise_for_status()


def _patch_discord_forum_starter_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(
            f'/channels/{thread_id}/messages/{thread_id}',
            json=payload,
        )
        response.raise_for_status()


def _post_discord_forum_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{thread_id}/messages',
            json=payload,
        )
        response.raise_for_status()
