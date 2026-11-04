"""
byceps.services.netsession_tourney.ranking_order
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Order of ranked participants: sort keys and tie-breakers (including the
Swiss head-to-head comparison).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

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
from .models import (
    ParticipantID,
    StageType,
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


def _sort_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    *,
    stage_type: str | None = None,
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ] | None = None,
    is_ffa_scoring_stage: bool,
) -> list[ParticipantID]:
    if not is_ffa_scoring_stage and stage_type == StageType.swiss.value:
        swiss_head_to_head_scores = _build_swiss_head_to_head_scores(
            rows_by_participant_id, head_to_head_winner_id_by_pair
        )
        return [
            participant_id
            for participant_id, _ in sorted(
                rows_by_participant_id.items(),
                key=lambda item: (
                    -item[1].get('wins', 0),
                    item[1].get('losses', 0),
                    -item[1].get('buchholz', 0),
                    -item[1].get('opponent_wl_sum', 0),
                    -item[1].get('second_order_sos', 0),
                    -swiss_head_to_head_scores.get(item[0], 0),
                    -item[1].get('round_diff', 0),
                    -item[1].get('round_wins', 0),
                    (
                        item[1]['seed']
                        if item[1]['seed'] is not None
                        else 999_999
                    ),
                    item[1]['created_at'],
                ),
            )
        ]

    if (
        not is_ffa_scoring_stage
        and stage_type == StageType.round_robin_groups.value
    ):
        tie_break_values_by_participant_id: dict[
            ParticipantID, tuple[int, int, int, int]
        ] = {}
        participants_by_points: dict[int, list[ParticipantID]] = defaultdict(list)
        for participant_id, row in rows_by_participant_id.items():
            participants_by_points[row.get('match_points', 0)].append(
                participant_id
            )

        for participant_ids in participants_by_points.values():
            direct_compare_scores = {
                participant_id: 0 for participant_id in participant_ids
            }
            if (
                len(participant_ids) == 2
                and head_to_head_winner_id_by_pair is not None
            ):
                winner_id = head_to_head_winner_id_by_pair.get(
                    frozenset(participant_ids)
                )
                if winner_id in direct_compare_scores:
                    direct_compare_scores[winner_id] = 1

            for participant_id in participant_ids:
                row = rows_by_participant_id[participant_id]
                tie_break_values_by_participant_id[participant_id] = (
                    row.get('match_points', 0),
                    direct_compare_scores[participant_id],
                    row.get('round_diff', 0),
                    row.get('round_wins', 0),
                )

        return [
            participant_id
            for participant_id, _ in sorted(
                rows_by_participant_id.items(),
                key=lambda item: (
                    -tie_break_values_by_participant_id[item[0]][0],
                    -tie_break_values_by_participant_id[item[0]][1],
                    -tie_break_values_by_participant_id[item[0]][2],
                    -tie_break_values_by_participant_id[item[0]][3],
                    (
                        item[1]['seed']
                        if item[1]['seed'] is not None
                        else 999_999
                    ),
                    item[1]['created_at'],
                ),
            )
        ]

    return [
        participant_id
        for participant_id, _ in sorted(
            rows_by_participant_id.items(),
            key=lambda item: (
                (
                    -item[1]['total_points']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    -item[1]['points']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    -item[1]['kills']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    (
                        item[1]['placement']
                        if item[1]['placement'] is not None
                        else 999_999
                    )
                    if is_ffa_scoring_stage
                    else 0
                ),
                -item[1]['wins'],
                item[1]['losses'],
                item[1]['seed'] if item[1]['seed'] is not None else 999_999,
                item[1]['created_at'],
            ),
        )
    ]


def _build_swiss_head_to_head_scores(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None,
) -> dict[ParticipantID, int]:
    scores_by_participant_id = {
        participant_id: 0 for participant_id in rows_by_participant_id
    }
    if head_to_head_winner_id_by_pair is None:
        return scores_by_participant_id

    participant_ids_by_base_tie_values: dict[
        tuple[int, int, int, int, int], list[ParticipantID]
    ] = defaultdict(list)
    for participant_id, row in rows_by_participant_id.items():
        participant_ids_by_base_tie_values[
            (
                row.get('wins', 0),
                row.get('losses', 0),
                row.get('buchholz', 0),
                row.get('opponent_wl_sum', 0),
                row.get('second_order_sos', 0),
            )
        ].append(participant_id)

    for participant_ids in participant_ids_by_base_tie_values.values():
        if len(participant_ids) != 2:
            continue

        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in scores_by_participant_id:
            scores_by_participant_id[winner_id] = 1

    return scores_by_participant_id
