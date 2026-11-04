"""
byceps.services.netsession_tourney.notification_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match labels used in notifications (e.g. upper/lower bracket wording for double elimination).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from byceps.database import db

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
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
    StageID,
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


def _build_double_elimination_notification_match_label(
    db_match: DbNetsessionTourneyMatch,
    stage_id: StageID,
) -> str:
    db_stage_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_stage_matches:
        return f'M #{db_match.match_no}'

    stage_match_ids = [db_stage_match.id for db_stage_match in db_stage_matches]
    db_stage_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(stage_match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()

    source_match_id_by_slot_id = {
        db_slot.id: db_slot.match_id for db_slot in db_stage_slots
    }
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]] = (
        defaultdict(list)
    )
    for db_slot in db_stage_slots:
        if db_slot.source_match_slot_id is None:
            continue
        source_match_id = source_match_id_by_slot_id.get(
            db_slot.source_match_slot_id
        )
        if source_match_id is None:
            continue
        incoming_by_match_id[db_slot.match_id].append(
            (source_match_id, db_slot.source_outcome)
        )

    labels_by_match_id = _build_double_elimination_notification_match_labels(
        db_stage_matches,
        incoming_by_match_id,
    )
    return labels_by_match_id.get(db_match.id, f'M #{db_match.match_no}')


def _build_double_elimination_notification_match_labels(
    db_stage_matches: list[DbNetsessionTourneyMatch],
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]],
) -> dict[MatchID, str]:
    sorted_matches = sorted(
        db_stage_matches,
        key=lambda match: (match.round_no, match.match_no),
    )
    stage_match_ids = {match.id for match in db_stage_matches}
    bracket_by_match_id: dict[MatchID, str] = {}

    changed = True
    while changed:
        changed = False
        for match in sorted_matches:
            incoming = [
                (source_match_id, outcome)
                for source_match_id, outcome in incoming_by_match_id.get(
                    match.id, []
                )
                if source_match_id in stage_match_ids
            ]
            bracket = bracket_by_match_id.get(match.id)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                source_brackets = {
                    bracket_by_match_id.get(source_match_id)
                    for source_match_id, _ in incoming
                }
                source_brackets.discard(None)

                if 'GF' in source_brackets:
                    next_bracket = 'GF'
                elif any(
                    _is_loser_notification_outcome(outcome)
                    for _, outcome in incoming
                ):
                    next_bracket = 'LB'
                elif source_brackets == {'WB'}:
                    next_bracket = 'WB'
                elif source_brackets == {'LB'}:
                    next_bracket = 'LB'
                elif source_brackets == {'WB', 'LB'}:
                    next_bracket = 'GF'

            if next_bracket != bracket:
                bracket_by_match_id[match.id] = next_bracket
                changed = True

    labels_by_match_id = {match.id: f'M #{match.match_no}' for match in db_stage_matches}

    gf_matches = sorted(
        [
            match
            for match in sorted_matches
            if bracket_by_match_id.get(match.id) == 'GF'
        ],
        key=lambda match: (match.round_no, match.match_no),
    )
    if gf_matches:
        if len(gf_matches) == 1:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
        elif len(gf_matches) == 2:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
            labels_by_match_id[gf_matches[1].id] = 'Double Grand Final'
        else:
            for index, match in enumerate(gf_matches, start=1):
                labels_by_match_id[match.id] = f'Grand Final #{index}'

    wb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'WB'
    ]
    lb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'LB'
    ]

    labels_by_match_id.update(
        _label_notification_bracket_matches(
            wb_matches,
            prefix='WB',
            semi_prefix='WB Semi',
            final_label='WB Final',
        )
    )
    labels_by_match_id.update(
        _label_notification_bracket_matches(
            lb_matches,
            prefix='LB',
            semi_prefix='LB Semi',
            final_label='LB Final',
        )
    )

    return labels_by_match_id


def _is_loser_notification_outcome(outcome: Any) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


def _label_notification_bracket_matches(
    matches: list[DbNetsessionTourneyMatch],
    *,
    prefix: str,
    semi_prefix: str,
    final_label: str,
) -> dict[MatchID, str]:
    if not matches:
        return {}

    labels_by_match_id: dict[MatchID, str] = {}
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = (
        defaultdict(list)
    )
    for match in matches:
        matches_by_round_no[match.round_no].append(match)

    sorted_round_nos = sorted(matches_by_round_no.keys())
    final_round_no = sorted_round_nos[-1]
    final_round_matches = sorted(
        matches_by_round_no[final_round_no],
        key=lambda match: match.match_no,
    )
    for index, match in enumerate(final_round_matches, start=1):
        labels_by_match_id[match.id] = (
            final_label
            if len(final_round_matches) == 1
            else f'{final_label} #{index}'
        )

    semi_round_no = sorted_round_nos[-2] if len(sorted_round_nos) >= 2 else None
    if semi_round_no is not None:
        semi_matches = sorted(
            matches_by_round_no[semi_round_no],
            key=lambda match: match.match_no,
        )
        for index, match in enumerate(semi_matches, start=1):
            labels_by_match_id[match.id] = f'{semi_prefix} #{index}'

    running_no = 1
    for round_no in sorted_round_nos:
        for match in sorted(
            matches_by_round_no[round_no],
            key=lambda current_match: current_match.match_no,
        ):
            if match.id in labels_by_match_id:
                continue
            labels_by_match_id[match.id] = f'{prefix} #{running_no}'
            running_no += 1

    return labels_by_match_id
