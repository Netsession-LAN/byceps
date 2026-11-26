"""
byceps.services.netsession_tourney.blueprints.site.swiss_public_round_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One round of the public Swiss bracket: pools with their matches and the
qualified/eliminated outcomes.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.score_parsing import (
    parse_numeric_score_value,
)

from .swiss_public_round_outcomes import _build_round_outcomes, SwissRenderData


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
