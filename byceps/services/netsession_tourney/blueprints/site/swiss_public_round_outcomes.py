"""
byceps.services.netsession_tourney.blueprints.site.swiss_public_round_outcomes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Outcome boxes (qualified, eliminated) of a logical Swiss round.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from uuid import UUID

from flask_babel import gettext

from .presentation_helpers import get_participant_image


@dataclass(frozen=True, kw_only=True)
class SwissRenderData:
    slots_by_match_id: Any
    results_by_match_id: Any
    slot_scores_by_match_id: Any
    participants_by_id: Any
    users_by_id: Any
    match_labels_by_id: Any


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
