"""
byceps.services.netsession_tourney.discord_result_summaries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Texts for Discord posts about match and tournament results.
"""

from __future__ import annotations

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
from .models import (
    ParticipantID,
    Stage,
    StageType,
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


def _build_discord_match_result_summary(
    *,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    occupied_slots = [
        db_slot
        for db_slot in sorted(db_slots, key=lambda item: item.slot_no)
        if db_slot.participant_id is not None
        and db_slot.participant_id in db_participants_by_id
    ]
    if not occupied_slots:
        return None

    is_ffa_stage = stage.type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }

    if is_ffa_stage:
        raw_placements = (
            ranking_data.get('placements')
            if isinstance(ranking_data, dict)
            else None
        )
        raw_points = (
            ranking_data.get('points')
            if isinstance(ranking_data, dict)
            else None
        )
        if not isinstance(raw_placements, dict):
            return None

        rows: list[dict[str, Any]] = []
        for db_slot in occupied_slots:
            participant = db_participants_by_id.get(db_slot.participant_id)
            if participant is None:
                continue

            placement = raw_placements.get(str(db_slot.slot_no))
            if placement is None:
                placement = raw_placements.get(db_slot.slot_no)
            if placement is None:
                continue

            points = None
            if isinstance(raw_points, dict):
                points = raw_points.get(str(db_slot.slot_no))
                if points is None:
                    points = raw_points.get(db_slot.slot_no)

            rows.append(
                {
                    'position': int(placement),
                    'participant_name': participant.name,
                    'points': points,
                }
            )

        if not rows:
            return None

        rows.sort(key=lambda item: (item['position'], item['participant_name']))
        return {'format': 'ffa', 'rows': rows}

    parsed_scores = _parse_match_result_slot_scores(
        db_slots, score_data, winner_slot=winner_slot
    )
    rows = []
    for db_slot in occupied_slots:
        participant = db_participants_by_id.get(db_slot.participant_id)
        if participant is None:
            continue

        rows.append(
            {
                'slot_no': db_slot.slot_no,
                'participant_name': participant.name,
                'score': parsed_scores.get(db_slot.slot_no),
                'is_winner': winner_slot == db_slot.slot_no,
            }
        )

    if not rows:
        return None

    rows.sort(
        key=lambda item: (
            0 if item['is_winner'] else 1,
            item['slot_no'],
        )
    )
    return {'format': 'duel', 'rows': rows}


def _build_discord_tournament_result_summary(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any] | None:
    participants_by_id = {
        participant.id: participant
        for participant in get_participants_for_tournament(
            db_tournament.party_id, db_tournament.id
        )
    }
    if not participants_by_id:
        return None

    stages = get_stages_for_tournament(db_tournament.party_id, db_tournament.id)
    for stage in reversed(stages):
        ranked_participant_ids_result = _get_ranked_participant_ids_for_stage(
            stage.id, db_tournament.id
        )
        if ranked_participant_ids_result.is_err():
            continue

        placements: list[dict[str, Any]] = []
        for position, participant_id in enumerate(
            ranked_participant_ids_result.unwrap()[:8], start=1
        ):
            participant = participants_by_id.get(participant_id)
            if participant is None:
                continue
            placements.append(
                {
                    'position': position,
                    'participant_name': participant.name,
                }
            )

        if placements:
            return {
                'stage_name': stage.name,
                'placements': placements,
            }

    return None


def _build_discord_tournament_finished_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    winner_name = placements[0][1]
    stage_name = str(result_summary.get('stage_name') or '').strip()
    lines = [
        f'**{tournament_title}**',
        f'Gewonnen hat **{winner_name}**.',
    ]
    if stage_name:
        lines.append(f'Gewertet wurde die Abschluss-Stage **{stage_name}**.')
    return '\n'.join(lines)


def _build_discord_tournament_finished_fields(
    payload_data: dict[str, Any],
) -> list[dict[str, Any]]:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return []

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return []

    fields: list[dict[str, Any]] = []
    stage_name = str(result_summary.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Abschluss-Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    podium_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[:3]
    ]
    if podium_lines:
        fields.append(
            {
                'name': 'Podium',
                'value': '\n'.join(podium_lines)[:1024],
                'inline': False,
            }
        )

    remaining_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[3:]
    ]
    if remaining_lines:
        fields.append(
            {
                'name': 'Weitere Plaetze',
                'value': '\n'.join(remaining_lines)[:1024],
                'inline': False,
            }
        )

    return fields


def _build_discord_match_completed_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    stage_name = str(payload_data.get('stage_name') or '').strip()
    match_label = str(payload_data.get('match_label') or '').strip()
    result_summary = payload_data.get('result_summary')

    lines = [f'**{tournament_title}**']
    if stage_name and match_label:
        lines.append(f'{stage_name} - {match_label} ist abgeschlossen.')
    elif match_label:
        lines.append(f'{match_label} ist abgeschlossen.')
    else:
        lines.append('Ein Match ist abgeschlossen.')

    if isinstance(result_summary, dict):
        rows = result_summary.get('rows')
        if isinstance(rows, list) and rows:
            winner_name = str(rows[0].get('participant_name') or '').strip()
            if winner_name:
                lines.append(f'Gewonnen hat **{winner_name}**.')

    return '\n'.join(lines)


def _build_discord_match_completed_fields(
    payload_data: dict[str, Any]
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    stage_name = str(payload_data.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    match_label = str(payload_data.get('match_label') or '').strip()
    if match_label:
        fields.append(
            {
                'name': 'Match',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return fields

    rows = result_summary.get('rows')
    if not isinstance(rows, list) or not rows:
        return fields

    if result_summary.get('format') == 'ffa':
        ranking_lines = []
        for row in rows[:8]:
            participant_name = str(row.get('participant_name') or '').strip()
            if not participant_name:
                continue
            try:
                position = int(row.get('position'))
            except (TypeError, ValueError):
                continue

            points = row.get('points')
            line = f'{position}. {participant_name}'
            if points is not None and str(points).strip():
                line += f' - {points} Pkt.'
            ranking_lines.append(line)

        if ranking_lines:
            fields.append(
                {
                    'name': 'Ranking',
                    'value': '\n'.join(ranking_lines)[:1024],
                    'inline': False,
                }
            )
    else:
        result_lines = []
        for row in rows[:8]:
            participant_name = str(row.get('participant_name') or '').strip()
            if not participant_name:
                continue
            score = row.get('score')
            score_suffix = (
                f' - {score}' if score is not None and str(score).strip() else ''
            )
            prefix = 'W' if row.get('is_winner') else '-'
            result_lines.append(f'{prefix} {participant_name}{score_suffix}')

        if result_lines:
            fields.append(
                {
                    'name': 'Ergebnis',
                    'value': '\n'.join(result_lines)[:1024],
                    'inline': False,
                }
            )

    return fields


def _normalize_discord_tournament_placements(
    raw_placements: Any,
) -> list[tuple[int, str]]:
    if not isinstance(raw_placements, list):
        return []

    normalized: list[tuple[int, str]] = []
    for item in raw_placements:
        if not isinstance(item, dict):
            continue

        participant_name = str(item.get('participant_name') or '').strip()
        if not participant_name:
            continue

        try:
            position = int(item.get('position'))
        except (TypeError, ValueError):
            continue

        if position < 1:
            continue

        normalized.append((position, participant_name))

    return normalized


def _format_discord_tournament_placement(
    position: int, participant_name: str
) -> str:
    marker = {1: '🥇', 2: '🥈', 3: '🥉'}.get(position, f'{position}.')
    return f'{marker} {participant_name}'
