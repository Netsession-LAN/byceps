"""
byceps.services.netsession_tourney.blueprints.site.swiss_public_round_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One round of the public Swiss bracket: pools with their matches and the
qualified/eliminated outcomes.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from uuid import UUID

from flask_babel import gettext

from byceps.services.netsession_tourney.score_parsing import (
    parse_numeric_score_value,
)

from .presentation_helpers import get_participant_image


@dataclass(frozen=True, kw_only=True)
class SwissRenderData:
    slots_by_match_id: Any
    results_by_match_id: Any
    slot_scores_by_match_id: Any
    participants_by_id: Any
    users_by_id: Any
    match_labels_by_id: Any


def build_logical_round(
    round_layout,
    round_matches,
    threshold,
    previous_round_match_id_by_participant_id,
    cumulative_points_by_participant_id,
    data: SwissRenderData,
) -> dict:
    round_no = round_layout['round_no']
    pool_views = _build_pool_views(
        round_layout,
        round_matches,
        threshold,
        previous_round_match_id_by_participant_id,
        data,
    )

    _add_round_points(cumulative_points_by_participant_id, round_matches, data)

    qualified_outcome, eliminated_outcome = _build_round_outcomes(
        round_no,
        pool_views,
        threshold,
        cumulative_points_by_participant_id,
        data,
    )

    return {
        'round_no': round_no,
        'pools': pool_views,
        'outcomes': [
            outcome
            for outcome in [qualified_outcome, eliminated_outcome]
            if outcome is not None
        ],
    }


# -------------------------------------------------------------------- #
# pools


def _build_pool_views(
    round_layout,
    round_matches,
    threshold,
    previous_round_match_id_by_participant_id,
    data: SwissRenderData,
) -> list[dict]:
    match_cursor = 0
    pool_views = []
    for pool in round_layout['pools']:
        pool_matches = round_matches[
            match_cursor : match_cursor + pool['match_count']
        ]
        match_cursor += pool['match_count']
        pool_views.append(
            _build_pool_view(
                round_layout['round_no'],
                pool,
                pool_matches,
                threshold,
                previous_round_match_id_by_participant_id,
                data,
            )
        )
    return pool_views


def _build_pool_view(
    round_no,
    pool,
    pool_matches,
    threshold,
    previous_round_match_id_by_participant_id,
    data: SwissRenderData,
) -> dict:
    pool_label = f'{pool["wins"]}-{pool["losses"]}'
    pool_items = [
        _build_pool_item(
            pool_match,
            pool_label,
            round_no,
            previous_round_match_id_by_participant_id,
            data,
        )
        for pool_match in pool_matches
    ]

    return {
        'id': f'swiss-round-{round_no}-{pool["wins"]}-{pool["losses"]}',
        'wins': pool['wins'],
        'losses': pool['losses'],
        'row_position': (threshold - 1) + pool['losses'] - pool['wins'],
        'label': pool_label,
        'tone': _get_pool_tone(pool),
        'participant_count': pool['participant_count'],
        'matches': pool_items,
        'winner_target_id': _get_winner_target_id(round_no, pool, threshold),
        'loser_target_id': _get_loser_target_id(round_no, pool, threshold),
    }


def _build_pool_item(
    pool_match,
    pool_label: str,
    round_no,
    previous_round_match_id_by_participant_id,
    data: SwissRenderData,
) -> dict:
    slots = sorted(
        data.slots_by_match_id.get(pool_match.id, []),
        key=lambda slot: slot.slot_no,
    )
    result = data.results_by_match_id.get(pool_match.id)
    slot_scores = data.slot_scores_by_match_id.get(pool_match.id, {})
    slot_views = [
        _build_slot_view(
            slot,
            slots,
            slot_scores,
            round_no,
            previous_round_match_id_by_participant_id,
            data.participants_by_id,
        )
        for slot in slots
    ]

    return {
        'match': pool_match,
        'slots': slot_views,
        'pool_label': pool_label,
        'result': result,
        'match_label': data.match_labels_by_id.get(
            pool_match.id,
            gettext('Match') + f' #{pool_match.match_no}',
        ),
    }


def _build_slot_view(
    slot,
    slots,
    slot_scores,
    round_no,
    previous_round_match_id_by_participant_id,
    participants_by_id,
) -> dict:
    participant = (
        participants_by_id.get(slot.participant_id)
        if slot.participant_id
        else None
    )
    is_bye = participant is None and any(
        other_slot.participant_id is not None for other_slot in slots
    )
    source_match_id = None
    if slot.participant_id is not None and round_no > 1:
        source_match_id = previous_round_match_id_by_participant_id.get(
            slot.participant_id
        )
    return {
        'slot_no': slot.slot_no,
        'participant': participant,
        'source_match_id': source_match_id,
        'is_bye': is_bye,
        'points': slot_scores.get(slot.slot_no),
    }


def _get_pool_tone(pool) -> str:
    if pool['wins'] == 0 and pool['losses'] == 0:
        return 'neutral'
    if pool['wins'] == pool['losses']:
        return 'warning'
    if pool['wins'] > pool['losses']:
        return 'positive'
    return 'danger'


def _get_winner_target_id(round_no, pool, threshold) -> str:
    if pool['wins'] + 1 >= threshold:
        return f'swiss-round-{round_no}-qualified'
    return f'swiss-round-{round_no + 1}-{pool["wins"] + 1}-{pool["losses"]}'


def _get_loser_target_id(round_no, pool, threshold) -> str:
    if pool['losses'] + 1 >= threshold:
        return f'swiss-round-{round_no}-eliminated'
    return f'swiss-round-{round_no + 1}-{pool["wins"]}-{pool["losses"] + 1}'


def _add_round_points(
    cumulative_points_by_participant_id, round_matches, data: SwissRenderData
) -> None:
    for round_match in round_matches:
        slot_scores = data.slot_scores_by_match_id.get(round_match.id, {})
        for slot in data.slots_by_match_id.get(round_match.id, []):
            if slot.participant_id is None:
                continue
            cumulative_points_by_participant_id[slot.participant_id] += (
                parse_numeric_score_value(slot_scores.get(slot.slot_no))
            )


# -------------------------------------------------------------------- #
# outcomes


def _build_round_outcomes(
    round_no,
    pool_views,
    threshold,
    cumulative_points_by_participant_id,
    data: SwissRenderData,
) -> tuple[dict | None, dict | None]:
    (
        qualified_count,
        eliminated_count,
        qualified_participant_ids,
        eliminated_participant_ids,
    ) = _collect_round_outcome_participants(pool_views, threshold, data)

    qualified_outcome = None
    eliminated_outcome = None
    if qualified_count:
        qualified_outcome = _build_qualified_outcome(
            round_no,
            pool_views,
            threshold,
            qualified_count,
            qualified_participant_ids,
            cumulative_points_by_participant_id,
            data,
        )
    if eliminated_count:
        eliminated_outcome = _build_eliminated_outcome(
            round_no,
            pool_views,
            threshold,
            eliminated_count,
            eliminated_participant_ids,
            cumulative_points_by_participant_id,
            data,
        )
    return qualified_outcome, eliminated_outcome


def _collect_round_outcome_participants(
    pool_views, threshold, data: SwissRenderData
) -> tuple[int, int, list, list]:
    qualified_count = 0
    eliminated_count = 0
    qualified_participant_ids = []
    eliminated_participant_ids = []
    for pool_view in pool_views:
        participant_count_in_pool = pool_view['participant_count']
        winner_count = math.ceil(participant_count_in_pool / 2)
        loser_count = participant_count_in_pool // 2
        reaches_qualified = pool_view['wins'] + 1 >= threshold
        reaches_eliminated = pool_view['losses'] + 1 >= threshold
        if reaches_qualified:
            qualified_count += winner_count
        if reaches_eliminated:
            eliminated_count += loser_count

        if not reaches_qualified and not reaches_eliminated:
            continue

        _collect_pool_outcome_participants(
            pool_view,
            reaches_qualified,
            reaches_eliminated,
            qualified_participant_ids,
            eliminated_participant_ids,
            data,
        )

    return (
        qualified_count,
        eliminated_count,
        qualified_participant_ids,
        eliminated_participant_ids,
    )


def _collect_pool_outcome_participants(
    pool_view,
    reaches_qualified: bool,
    reaches_eliminated: bool,
    qualified_participant_ids: list,
    eliminated_participant_ids: list,
    data: SwissRenderData,
) -> None:
    for pool_item in pool_view['matches']:
        pool_match = pool_item['match']
        result = data.results_by_match_id.get(pool_match.id)
        if result is None or result.winner_slot is None:
            continue

        slots = data.slots_by_match_id.get(pool_match.id, [])
        winner_slot, loser_slots = _split_winner_and_loser_slots(slots, result)

        if reaches_qualified:
            _append_winner_participant_id(
                qualified_participant_ids, winner_slot
            )

        if reaches_eliminated:
            _extend_loser_participant_ids(
                eliminated_participant_ids, loser_slots
            )


def _split_winner_and_loser_slots(slots, result):
    slot_by_no = {slot.slot_no: slot for slot in slots}
    winner_slot = slot_by_no.get(result.winner_slot)
    loser_slots = [
        slot
        for slot in slots
        if slot.slot_no != result.winner_slot
        and slot.participant_id is not None
    ]
    return winner_slot, loser_slots


def _extend_loser_participant_ids(participant_ids: list, loser_slots) -> None:
    participant_ids.extend(
        slot.participant_id
        for slot in loser_slots
        if slot.participant_id is not None
    )


def _append_winner_participant_id(participant_ids: list, winner_slot) -> None:
    if winner_slot is not None and winner_slot.participant_id is not None:
        participant_ids.append(winner_slot.participant_id)


def _build_qualified_outcome(
    round_no,
    pool_views,
    threshold,
    qualified_count,
    qualified_participant_ids,
    cumulative_points_by_participant_id,
    data: SwissRenderData,
) -> dict:
    qualified_source_row_position = next(
        (
            pool_view['row_position']
            for pool_view in pool_views
            if pool_view['wins'] + 1 >= threshold
        ),
        0,
    )
    qualified_row_position = qualified_source_row_position - 0.85
    return {
        'id': f'swiss-round-{round_no}-qualified',
        'label': gettext('Weiter'),
        'tone': 'qualified',
        'count': qualified_count,
        'participants': _build_outcome_participant_rows(
            qualified_participant_ids,
            cumulative_points_by_participant_id,
            data,
        ),
        'pending_count': max(
            0,
            qualified_count - len(set(qualified_participant_ids)),
        ),
        'row_position': qualified_row_position,
    }


def _build_eliminated_outcome(
    round_no,
    pool_views,
    threshold,
    eliminated_count,
    eliminated_participant_ids,
    cumulative_points_by_participant_id,
    data: SwissRenderData,
) -> dict:
    eliminated_source_row_position = next(
        (
            pool_view['row_position']
            for pool_view in pool_views
            if pool_view['losses'] + 1 >= threshold
        ),
        (threshold - 1) * 2,
    )
    eliminated_row_position = eliminated_source_row_position + 0.85
    return {
        'id': f'swiss-round-{round_no}-eliminated',
        'label': gettext('Raus'),
        'tone': 'eliminated',
        'count': eliminated_count,
        'participants': _build_outcome_participant_rows(
            eliminated_participant_ids,
            cumulative_points_by_participant_id,
            data,
        ),
        'pending_count': max(
            0,
            eliminated_count - len(set(eliminated_participant_ids)),
        ),
        'row_position': eliminated_row_position,
    }


def _build_outcome_participant_rows(
    participant_ids: list[UUID],
    cumulative_points_by_participant_id: dict,
    data: SwissRenderData,
) -> list[dict]:
    rows = []
    seen_participant_ids = set()
    for participant_id in participant_ids:
        if participant_id in seen_participant_ids:
            continue
        seen_participant_ids.add(participant_id)

        participant = data.participants_by_id.get(participant_id)
        if participant is None:
            continue

        rows.append(
            _build_outcome_participant_row(
                participant,
                cumulative_points_by_participant_id.get(participant_id, 0),
                data.users_by_id,
            )
        )

    rows.sort(
        key=lambda item: (
            -item['points_value'],
            item['participant'].name.lower(),
        )
    )
    return rows


def _build_outcome_participant_row(participant, points, users_by_id) -> dict:
    image_url, image_alt = get_participant_image(participant, users_by_id)
    return {
        'participant': participant,
        'image_url': image_url,
        'image_alt': image_alt,
        'points': str(points),
        'points_value': points,
    }
