"""
byceps.services.netsession_tourney.blueprints.site.swiss_public_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any
from uuid import UUID

from flask_babel import gettext

from ...models import StageType
from ...service import (
    _build_swiss_round_layout,
    _get_round_count_for_swiss_stage,
    _get_swiss_threshold_for_stage,
)


def _build_swiss_bracket_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    slot_scores_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    stages_by_id,
):
    def _parse_numeric_points(value) -> int:
        if value is None:
            return 0
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def _build_outcome_participant_rows(
        participant_ids: list[UUID], cumulative_points_by_participant_id: dict
    ) -> list[dict]:
        rows = []
        seen_participant_ids = set()
        for participant_id in participant_ids:
            if participant_id in seen_participant_ids:
                continue
            seen_participant_ids.add(participant_id)

            participant = participants_by_id.get(participant_id)
            if participant is None:
                continue

            image_url = None
            image_alt = None
            if participant.type.value == 'team' and participant.logo_url:
                image_url = participant.logo_url
                image_alt = gettext('Team-Logo')
            elif participant.user_id is not None:
                user = users_by_id.get(participant.user_id)
                if user is not None and user.avatar_url:
                    image_url = user.avatar_url
                    image_alt = gettext('Avatar')

            points = cumulative_points_by_participant_id.get(participant_id, 0)
            rows.append(
                {
                    'participant': participant,
                    'image_url': image_url,
                    'image_alt': image_alt,
                    'points': str(points),
                    'points_value': points,
                }
            )

        rows.sort(
            key=lambda item: (
                -item['points_value'],
                item['participant'].name.lower(),
            )
        )
        return rows

    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for stage_id, stage_matches in sorted(
        matches_by_stage_id.items(),
        key=lambda item: (
            stages_by_id.get(item[0]).order_no if stages_by_id.get(item[0]) else 999,
            stages_by_id.get(item[0]).name if stages_by_id.get(item[0]) else '',
        ),
    ):
        stage = stages_by_id.get(stage_id)
        if stage is None or stage.type != StageType.swiss:
            continue

        participant_count = len(
            {
                slot.participant_id
                for slots in (
                    slots_by_match_id.get(match.id, []) for match in stage_matches
                )
                for slot in slots
                if slot.participant_id is not None
            }
        )
        round_count = _get_round_count_for_swiss_stage(
            stage, participant_count=participant_count
        )
        layout = _build_swiss_round_layout(participant_count, round_count)
        threshold = _get_swiss_threshold_for_stage(
            stage, participant_count=participant_count
        )
        matches_by_round_no = defaultdict(list)
        for match in stage_matches:
            matches_by_round_no[match.round_no].append(match)

        previous_round_match_id_by_participant_id: dict[Any, Any] = {}
        cumulative_points_by_participant_id = defaultdict(int)
        logical_rounds = []
        for round_layout in layout:
            round_matches = sorted(
                matches_by_round_no.get(round_layout['round_no'], []),
                key=lambda match: match.match_no,
            )
            match_cursor = 0
            pool_views = []
            qualified_outcome = None
            eliminated_outcome = None
            for pool in round_layout['pools']:
                pool_label = f"{pool['wins']}-{pool['losses']}"
                pool_matches = round_matches[
                    match_cursor : match_cursor + pool['match_count']
                ]
                match_cursor += pool['match_count']
                pool_items = []
                for pool_match in pool_matches:
                    slots = sorted(
                        slots_by_match_id.get(pool_match.id, []),
                        key=lambda slot: slot.slot_no,
                    )
                    result = results_by_match_id.get(pool_match.id)
                    slot_scores = slot_scores_by_match_id.get(pool_match.id, {})
                    slot_views = []
                    for slot in slots:
                        participant = (
                            participants_by_id.get(slot.participant_id)
                            if slot.participant_id
                            else None
                        )
                        is_bye = (
                            participant is None
                            and any(
                                other_slot.participant_id is not None
                                for other_slot in slots
                            )
                        )
                        source_match_id = None
                        if (
                            slot.participant_id is not None
                            and round_layout['round_no'] > 1
                        ):
                            source_match_id = (
                                previous_round_match_id_by_participant_id.get(
                                    slot.participant_id
                                )
                            )
                        slot_views.append(
                            {
                                'slot_no': slot.slot_no,
                                'participant': participant,
                                'source_match_id': source_match_id,
                                'is_bye': is_bye,
                                'points': slot_scores.get(slot.slot_no),
                            }
                        )

                    pool_items.append(
                        {
                            'match': pool_match,
                            'slots': slot_views,
                            'pool_label': pool_label,
                            'result': result,
                            'match_label': match_labels_by_id.get(
                                pool_match.id,
                                gettext('Match') + f' #{pool_match.match_no}',
                            ),
                        }
                    )

                if pool['wins'] == 0 and pool['losses'] == 0:
                    tone = 'neutral'
                elif pool['wins'] == pool['losses']:
                    tone = 'warning'
                elif pool['wins'] > pool['losses']:
                    tone = 'positive'
                else:
                    tone = 'danger'

                winner_target_id = (
                    f"swiss-round-{round_layout['round_no']}-qualified"
                    if pool['wins'] + 1 >= threshold
                    else f"swiss-round-{round_layout['round_no'] + 1}-{pool['wins'] + 1}-{pool['losses']}"
                )
                loser_target_id = (
                    f"swiss-round-{round_layout['round_no']}-eliminated"
                    if pool['losses'] + 1 >= threshold
                    else f"swiss-round-{round_layout['round_no'] + 1}-{pool['wins']}-{pool['losses'] + 1}"
                )

                pool_views.append(
                    {
                        'id': f"swiss-round-{round_layout['round_no']}-{pool['wins']}-{pool['losses']}",
                        'wins': pool['wins'],
                        'losses': pool['losses'],
                        'row_position': (threshold - 1) + pool['losses'] - pool['wins'],
                        'label': pool_label,
                        'tone': tone,
                        'participant_count': pool['participant_count'],
                        'matches': pool_items,
                        'winner_target_id': winner_target_id,
                        'loser_target_id': loser_target_id,
                    }
                )

            for round_match in round_matches:
                slot_scores = slot_scores_by_match_id.get(round_match.id, {})
                for slot in slots_by_match_id.get(round_match.id, []):
                    if slot.participant_id is None:
                        continue
                    cumulative_points_by_participant_id[slot.participant_id] += (
                        _parse_numeric_points(slot_scores.get(slot.slot_no))
                    )

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

                for pool_item in pool_view['matches']:
                    pool_match = pool_item['match']
                    result = results_by_match_id.get(pool_match.id)
                    if result is None or result.winner_slot is None:
                        continue

                    slots = slots_by_match_id.get(pool_match.id, [])
                    slot_by_no = {slot.slot_no: slot for slot in slots}
                    winner_slot = slot_by_no.get(result.winner_slot)
                    loser_slots = [
                        slot
                        for slot in slots
                        if slot.slot_no != result.winner_slot
                        and slot.participant_id is not None
                    ]

                    if (
                        reaches_qualified
                        and winner_slot is not None
                        and winner_slot.participant_id is not None
                    ):
                        qualified_participant_ids.append(winner_slot.participant_id)

                    if reaches_eliminated:
                        eliminated_participant_ids.extend(
                            slot.participant_id
                            for slot in loser_slots
                            if slot.participant_id is not None
                        )

            if qualified_count:
                qualified_source_row_position = next(
                    (
                        pool_view['row_position']
                        for pool_view in pool_views
                        if pool_view['wins'] + 1 >= threshold
                    ),
                    0,
                )
                qualified_row_position = qualified_source_row_position - 0.85
                qualified_outcome = {
                    'id': f"swiss-round-{round_layout['round_no']}-qualified",
                    'label': gettext('Qualified'),
                    'tone': 'qualified',
                    'count': qualified_count,
                    'participants': _build_outcome_participant_rows(
                        qualified_participant_ids,
                        cumulative_points_by_participant_id,
                    ),
                    'pending_count': max(
                        0,
                        qualified_count - len(set(qualified_participant_ids)),
                    ),
                    'row_position': qualified_row_position,
                }
            if eliminated_count:
                eliminated_source_row_position = next(
                    (
                        pool_view['row_position']
                        for pool_view in pool_views
                        if pool_view['losses'] + 1 >= threshold
                    ),
                    (threshold - 1) * 2,
                )
                eliminated_row_position = eliminated_source_row_position + 0.85
                eliminated_outcome = {
                    'id': f"swiss-round-{round_layout['round_no']}-eliminated",
                    'label': gettext('Eliminated'),
                    'tone': 'eliminated',
                    'count': eliminated_count,
                    'participants': _build_outcome_participant_rows(
                        eliminated_participant_ids,
                        cumulative_points_by_participant_id,
                    ),
                    'pending_count': max(
                        0,
                        eliminated_count - len(set(eliminated_participant_ids)),
                    ),
                    'row_position': eliminated_row_position,
                }

            logical_rounds.append(
                {
                    'round_no': round_layout['round_no'],
                    'pools': pool_views,
                    'outcomes': [
                        outcome
                        for outcome in [qualified_outcome, eliminated_outcome]
                        if outcome is not None
                    ],
                }
            )

            previous_round_match_id_by_participant_id = {
                slot.participant_id: match.id
                for match in round_matches
                for slot in slots_by_match_id.get(match.id, [])
                if slot.participant_id is not None
            }

        rounds = []
        for index, logical_round in enumerate(logical_rounds):
            incoming_outcomes = (
                logical_rounds[index - 1]['outcomes'] if index > 0 else []
            )
            blocks = [
                {'kind': 'outcome', 'item': outcome}
                for outcome in incoming_outcomes
            ] + [
                {'kind': 'pool', 'item': pool_view}
                for pool_view in logical_round['pools']
            ]
            rounds.append(
                {
                    'round_no': logical_round['round_no'],
                    'display_title': gettext('Runde')
                    + f' {logical_round["round_no"]}',
                    'is_sidecar': False,
                    'pools': logical_round['pools'],
                    'outcomes': incoming_outcomes,
                    'blocks': blocks,
                }
            )

        if logical_rounds and logical_rounds[-1]['outcomes']:
            rounds.append(
                {
                    'round_no': None,
                    'display_title': '',
                    'is_sidecar': True,
                    'pools': [],
                    'outcomes': logical_rounds[-1]['outcomes'],
                    'blocks': [
                        {'kind': 'outcome', 'item': outcome}
                        for outcome in logical_rounds[-1]['outcomes']
                    ],
                }
            )

        sections.append(
            {
                'key': str(stage_id),
                'title': stage.name,
                'rounds': rounds,
            }
        )

    return sections
