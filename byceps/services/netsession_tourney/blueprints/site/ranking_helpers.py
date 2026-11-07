"""
byceps.services.netsession_tourney.blueprints.site.ranking_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from ...models import MatchState, StageType
from .match_helpers import (
    is_skipped_double_grand_final_result,
    _parse_slot_scores,
)
from ...score_parsing import parse_numeric_score_value
from ...score_parsing import get_ffa_points_per_kill


def build_ffa_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    stages_by_id,
):
    rows_by_participant_id = {
        participant.id: {
            'participant': participant,
            'total_points': 0,
            'points': 0,
            'wins': 0,
            'played': 0,
            'kills': 0,
            'placement': None,
        }
        for participant in participants
    }

    for match in matches:
        result = results_by_match_id.get(match.id)
        if result is None:
            continue

        stage = stages_by_id.get(match.stage_id)
        points_per_kill = get_ffa_points_per_kill(
            stage.settings if stage is not None else None
        )
        slots = slots_by_match_id.get(match.id, [])
        placement_by_slot_no = {}
        points_by_slot_no = {}
        if isinstance(result.ranking, dict):
            raw_placements = result.ranking.get('placements')
            if isinstance(raw_placements, dict):
                for slot in slots:
                    raw_value = raw_placements.get(str(slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_placements.get(slot.slot_no)
                    try:
                        placement_by_slot_no[slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue
            raw_points = result.ranking.get('points')
            if isinstance(raw_points, dict):
                for slot in slots:
                    raw_value = raw_points.get(str(slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_points.get(slot.slot_no)
                    try:
                        points_by_slot_no[slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue

        slot_scores = _parse_slot_scores(slots, result)
        for slot in slots:
            if slot.participant_id is None:
                continue

            row = rows_by_participant_id.get(slot.participant_id)
            if row is None:
                continue

            row['played'] += 1
            row['points'] += points_by_slot_no.get(slot.slot_no, 0)
            if result.winner_slot == slot.slot_no:
                row['wins'] += 1

            try:
                row['kills'] += int(slot_scores.get(slot.slot_no, '0'))
            except ValueError:
                pass

            row['total_points'] = row['points'] + (
                row['kills'] * points_per_kill
            )

            placement = placement_by_slot_no.get(slot.slot_no)
            if placement is None:
                continue
            if row['placement'] is None or placement < row['placement']:
                row['placement'] = placement

    if not any(row['played'] for row in rows_by_participant_id.values()):
        return []

    rows = sorted(
        rows_by_participant_id.values(),
        key=lambda row: (
            -row['total_points'],
            -row['points'],
            -row['kills'],
            row['placement'] if row['placement'] is not None else 999999,
            row['participant'].seed or 999999,
            row['participant'].name.lower(),
        ),
    )

    ranking_rows = []
    rank = 0
    last_sort_value = None
    for index, row in enumerate(rows, start=1):
        sort_value = (
            row['total_points'],
            row['points'],
            row['kills'],
            row['placement'] if row['placement'] is not None else 999999,
        )
        if sort_value != last_sort_value:
            rank = index
            last_sort_value = sort_value
        ranking_rows.append({'rank': rank, **row})

    return ranking_rows


def build_flatout2_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    get_ffa_placement_by_slot_no,
):
    rows_by_participant_id = {
        participant.id: {
            'participant': participant,
            'wins': 0,
            'played': 0,
            'best_placement': None,
        }
        for participant in participants
    }

    for match in matches:
        result = results_by_match_id.get(match.id)
        if result is None:
            continue

        slots = slots_by_match_id.get(match.id, [])
        placement_by_slot_no = get_ffa_placement_by_slot_no(result, slots)
        for slot in slots:
            if slot.participant_id is None:
                continue

            row = rows_by_participant_id.get(slot.participant_id)
            if row is None:
                continue

            row['played'] += 1
            if result.winner_slot == slot.slot_no:
                row['wins'] += 1

            placement = placement_by_slot_no.get(slot.slot_no)
            if placement is None:
                continue
            if (
                row['best_placement'] is None
                or placement < row['best_placement']
            ):
                row['best_placement'] = placement

    if not any(row['played'] for row in rows_by_participant_id.values()):
        return []

    rows = sorted(
        rows_by_participant_id.values(),
        key=lambda row: (
            -row['wins'],
            row['best_placement'] if row['best_placement'] is not None else 999999,
            row['participant'].seed or 999999,
            row['participant'].name.lower(),
        ),
    )

    ranking_rows = []
    rank = 0
    last_sort_value = None
    for index, row in enumerate(rows, start=1):
        sort_value = (
            row['wins'],
            row['best_placement'] if row['best_placement'] is not None else 999999,
        )
        if sort_value != last_sort_value:
            rank = index
            last_sort_value = sort_value
        ranking_rows.append({'rank': rank, **row})

    return ranking_rows


def build_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    *,
    stage_type: StageType | None = None,
):
    stats_by_participant_id = {
        participant.id: {
            'participant': participant,
            'wins': 0,
            'losses': 0,
            'played': 0,
            'match_points': 0,
            'round_wins': 0,
            'round_losses': 0,
            'round_diff': 0,
            'buchholz': 0,
            'opponent_wl_sum': 0,
            'second_order_sos': 0,
        }
        for participant in participants
    }
    head_to_head_winner_id_by_pair = {}
    opponent_ids_by_participant_id = defaultdict(list)

    for match in matches:
        result = results_by_match_id.get(match.id)
        if is_skipped_double_grand_final_result(result):
            continue
        slots = slots_by_match_id.get(match.id, [])
        slot_by_no = {slot.slot_no: slot for slot in slots}
        slot_scores = _parse_slot_scores(slots, result)
        participant_ids = [
            slot.participant_id for slot in slots if slot.participant_id is not None
        ]
        if len(participant_ids) < 2:
            continue

        if result is not None and result.winner_slot is not None:
            winner_slot = slot_by_no.get(result.winner_slot)
            winner_id = winner_slot.participant_id if winner_slot else None
        else:
            winner_id = None
        is_walkover_result = (
            stage_type == StageType.swiss
            and _is_walkover_result(result)
        )

        for participant_id in participant_ids:
            row = stats_by_participant_id.get(participant_id)
            if row is None:
                continue
            if result is not None:
                row['played'] += 1
            if winner_id is not None:
                if participant_id == winner_id:
                    row['wins'] += 1
                    row['match_points'] += 3
                else:
                    row['losses'] += 1

        if len(participant_ids) != 2:
            continue

        ordered_slots = [
            slot
            for slot in sorted(slots, key=lambda slot: slot.slot_no)
            if slot.participant_id is not None
        ]
        if len(ordered_slots) != 2:
            continue

        participant_a_id = ordered_slots[0].participant_id
        participant_b_id = ordered_slots[1].participant_id
        if (
            participant_a_id is not None
            and participant_b_id is not None
            and not is_walkover_result
        ):
            opponent_ids_by_participant_id[participant_a_id].append(
                participant_b_id
            )
            opponent_ids_by_participant_id[participant_b_id].append(
                participant_a_id
            )

        if winner_id in participant_ids and not is_walkover_result:
            head_to_head_winner_id_by_pair[
                frozenset(participant_ids)
            ] = winner_id

        if is_walkover_result:
            continue

        for slot in ordered_slots:
            participant_id = slot.participant_id
            if participant_id is None:
                continue

            rounds_won = parse_numeric_score_value(slot_scores.get(slot.slot_no))
            rounds_lost = sum(
                parse_numeric_score_value(slot_scores.get(other_slot.slot_no))
                for other_slot in ordered_slots
                if other_slot.slot_no != slot.slot_no
            )
            row = stats_by_participant_id.get(participant_id)
            if row is not None:
                row['round_wins'] += rounds_won
                row['round_losses'] += rounds_lost
                row['round_diff'] = row['round_wins'] - row['round_losses']

    for participant_id, row in stats_by_participant_id.items():
        row['buchholz'] = sum(
            stats_by_participant_id.get(opponent_id, {}).get('wins', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
        row['opponent_wl_sum'] = sum(
            stats_by_participant_id.get(opponent_id, {}).get('wins', 0)
            - stats_by_participant_id.get(opponent_id, {}).get('losses', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
    for participant_id, row in stats_by_participant_id.items():
        row['second_order_sos'] = sum(
            stats_by_participant_id.get(opponent_id, {}).get(
                'opponent_wl_sum', 0
            )
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )

    if not any(row['played'] for row in stats_by_participant_id.values()):
        return []

    rows = list(stats_by_participant_id.values())
    if stage_type == StageType.swiss:
        swiss_head_to_head_scores = _build_swiss_head_to_head_scores(
            rows, head_to_head_winner_id_by_pair
        )
        rows = sorted(
            rows,
            key=lambda row: (
                -row['wins'],
                row['losses'],
                -row['buchholz'],
                -row['opponent_wl_sum'],
                -row['second_order_sos'],
                -swiss_head_to_head_scores.get(row['participant'].id, 0),
                -row['round_diff'],
                -row['round_wins'],
                row['participant'].seed or 999999,
                row['participant'].name.lower(),
            ),
        )

        ranking_rows = []
        for index, row in enumerate(rows, start=1):
            ranking_rows.append(
                {
                    'rank': index,
                    **row,
                }
            )

        return ranking_rows

    participant_ids_by_match_points = defaultdict(list)
    for row in rows:
        participant_ids_by_match_points[row['match_points']].append(
            row['participant'].id
        )

    tie_break_values_by_participant_id = {}
    for participant_ids in participant_ids_by_match_points.values():
        direct_compare_scores = {
            participant_id: 0 for participant_id in participant_ids
        }
        if len(participant_ids) == 2:
            winner_id = head_to_head_winner_id_by_pair.get(
                frozenset(participant_ids)
            )
            if winner_id in direct_compare_scores:
                direct_compare_scores[winner_id] = 1

        for participant_id in participant_ids:
            row = stats_by_participant_id[participant_id]
            tie_break_values_by_participant_id[participant_id] = (
                row['match_points'],
                direct_compare_scores[participant_id],
                row['round_diff'],
                row['round_wins'],
            )

    rows = sorted(
        rows,
        key=lambda row: (
            -tie_break_values_by_participant_id[row['participant'].id][0],
            -tie_break_values_by_participant_id[row['participant'].id][1],
            -tie_break_values_by_participant_id[row['participant'].id][2],
            -tie_break_values_by_participant_id[row['participant'].id][3],
            row['participant'].seed or 999999,
            row['participant'].name.lower(),
        ),
    )

    ranking_rows = []
    rank = 0
    last_sort_value = None
    for index, row in enumerate(rows, start=1):
        sort_value = tie_break_values_by_participant_id[row['participant'].id]
        if sort_value != last_sort_value:
            rank = index
            last_sort_value = sort_value

        ranking_rows.append(
            {
                'rank': rank,
                **row,
            }
        )

    return ranking_rows


def _is_walkover_result(result) -> bool:
    if result is None or not isinstance(result.score, dict):
        return False

    return bool(result.score.get('walkover'))


def _build_swiss_head_to_head_scores(rows, head_to_head_winner_id_by_pair):
    scores_by_participant_id = {
        row['participant'].id: 0 for row in rows
    }
    participant_ids_by_base_tie_values = defaultdict(list)
    for row in rows:
        participant_ids_by_base_tie_values[
            (
                row['wins'],
                row['losses'],
                row['buchholz'],
                row.get('opponent_wl_sum', 0),
                row.get('second_order_sos', 0),
            )
        ].append(row['participant'].id)

    for participant_ids in participant_ids_by_base_tie_values.values():
        if len(participant_ids) != 2:
            continue

        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in scores_by_participant_id:
            scores_by_participant_id[winner_id] = 1

    return scores_by_participant_id


def _build_swiss_ranking_groups(ranking_rows) -> list[dict]:
    groups = []
    current_group = None

    for row in ranking_rows:
        record = (row['wins'], row['losses'])
        if current_group is None or current_group['record'] != record:
            current_group = {
                'record': record,
                'label': f'{record[0]}-{record[1]}',
                'wins': record[0],
                'losses': record[1],
                'rows': [],
            }
            groups.append(current_group)

        current_group['rows'].append(row)

    return groups


def has_rankable_results(
    matches,
    slots_by_match_id,
    results_by_match_id,
):
    for match in matches:
        if not any(
            slot.participant_id is not None
            for slot in slots_by_match_id.get(match.id, [])
        ):
            continue

        result = results_by_match_id.get(match.id)
        if result is None or is_skipped_double_grand_final_result(result):
            continue

        return True

    return False


def are_all_rankable_matches_completed(
    matches,
    slots_by_match_id,
):
    relevant_matches = [
        match
        for match in matches
        if any(
            slot.participant_id is not None
            for slot in slots_by_match_id.get(match.id, [])
        )
    ]

    if not relevant_matches:
        return False

    return all(match.state == MatchState.completed for match in relevant_matches)
