"""
byceps.services.netsession_tourney.discord_payloads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Payloads of Discord forum posts and events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
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
    ParticipantID,
    Stage,
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


def _build_discord_tournament_finished_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'slug': db_tournament.slug}
    result_summary = _build_discord_tournament_result_summary(db_tournament)
    if result_summary:
        payload['result_summary'] = result_summary
    return payload


def _build_discord_match_completed_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_match: DbNetsessionTourneyMatch,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'stage_name': stage.name,
        'match_label': f'Match #{db_match.match_no}',
        'url': _build_site_match_path(db_tournament.slug, db_match.id),
    }

    result_summary = _build_discord_match_result_summary(
        stage=stage,
        db_slots=db_slots,
        db_participants_by_id=db_participants_by_id,
        winner_slot=winner_slot,
        score_data=score_data,
        ranking_data=ranking_data,
    )
    if result_summary:
        payload['result_summary'] = result_summary

    return payload


def _build_discord_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_row: DbNetsessionTourneyDiscordOutbox,
) -> dict[str, Any]:
    payload_data = db_row.payload_json or {}
    event_name = db_row.event_name
    title = db_tournament.title
    url = _build_absolute_notification_url(
        db_tournament.party_id, _build_site_tournament_overview_path(db_tournament.slug)
    )
    brand_icon_url = _build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )
    color = 0xFF2B00
    description = 'Es gibt ein neues Turnier-Update.'

    if event_name == 'manual_announcement':
        embed_title = 'Turnier-Update'
        description = str(payload_data.get('body') or '').strip() or description
        title = str(payload_data.get('title') or '').strip() or title
        custom_url = str(payload_data.get('url') or '').strip()
        if custom_url:
            url = _build_absolute_notification_url(
                db_tournament.party_id, custom_url
            )
    elif event_name == 'match_completed':
        embed_title = 'Match beendet'
        description = _build_discord_match_completed_description(
            title, payload_data
        )
        custom_url = str(payload_data.get('url') or '').strip()
        if custom_url:
            url = _build_absolute_notification_url(
                db_tournament.party_id, custom_url
            )
        color = 0x3B82F6
    elif event_name == 'stage_started':
        stage_name = str(payload_data.get('stage_name') or '').strip()
        embed_title = 'Stage gestartet'
        description = (
            f'**{title}**\n{stage_name} ist gestartet.'
            if stage_name
            else f'**{title}**\nEine neue Stage ist gestartet.'
        )
        title = stage_name or title
        color = 0xF97316
    elif event_name == 'tournament_finished':
        embed_title = 'Turnier beendet'
        description = _build_discord_tournament_finished_description(
            title, payload_data
        )
        color = 0x10B981
    elif event_name == 'tournament_canceled':
        embed_title = 'Turnier abgesagt'
        description = f'**{title}**\nDas Turnier wurde abgesagt.'
        color = 0xEF4444
    elif event_name == 'tournament_live':
        embed_title = 'Turnier live'
        description = f'**{title}**\nDas Turnier ist jetzt live.'
    else:
        embed_title = 'Turnier-Update'
        description = f'**{title}**\n{description}'

    fields = [
        {'name': 'Turnier', 'value': db_tournament.title[:1024], 'inline': True},
        {'name': 'Ereignis', 'value': embed_title[:1024], 'inline': True},
    ]
    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnierseite öffnen]({url})',
                'inline': False,
            }
        )
    if event_name == 'tournament_finished':
        fields.extend(
            _build_discord_tournament_finished_fields(payload_data)
        )
    elif event_name == 'match_completed':
        fields.extend(_build_discord_match_completed_fields(payload_data))

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': embed_title[:256],
        'description': description[:4096],
        'color': color,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_row.created_at.replace(microsecond=0).isoformat() + 'Z',
    }
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _build_discord_forum_thread_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    url = _build_absolute_notification_url(
        db_tournament.party_id, _build_site_tournament_overview_path(db_tournament.slug)
    )
    brand_icon_url = _build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )
    image_url = (
        _build_absolute_notification_url(
            db_tournament.party_id, db_tournament.discord_forum_image_url
        )
        if db_tournament.discord_forum_image_url
        else None
    )
    description_lines = [f'**{db_tournament.title}**']
    if db_tournament.subtitle:
        description_lines.append(db_tournament.subtitle)
    description_lines.append(
        'Der Discord-Thread für dieses Turnier wurde eingerichtet.'
    )

    fields = [
        {'name': 'Turnier', 'value': db_tournament.title[:1024], 'inline': True},
    ]
    if db_tournament.game:
        fields.append(
            {'name': 'Spiel', 'value': db_tournament.game[:1024], 'inline': True}
        )
    if db_tournament.starts_at is not None:
        fields.append(
            {
                'name': 'Start',
                'value': db_tournament.starts_at.strftime('%d.%m.%Y %H:%M')[:1024],
                'inline': True,
            }
        )
    if url:
        fields.append(
            {
                'name': 'Link',
                'value': f'[Turnierseite öffnen]({url})',
                'inline': False,
            }
        )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': db_tournament.title[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url
    if image_url:
        embed['image'] = {'url': image_url}

    payload: dict[str, Any] = {
        'name': db_tournament.title[:100],
        'auto_archive_duration': 10080,
        'message': {
            'allowed_mentions': {'parse': []},
            'embeds': [embed],
        },
    }
    if db_tournament.discord_applied_tag_ids:
        payload['applied_tags'] = db_tournament.discord_applied_tag_ids

    return payload
