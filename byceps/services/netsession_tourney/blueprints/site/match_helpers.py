"""
byceps.services.netsession_tourney.blueprints.site.match_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from byceps.util.uuid import generate_uuid7

from ...models import StageType
from .double_elimination_rendering import (
    build_double_elimination_match_labels,
)
from .ffa_single_elimination_rendering import (
    build_ffa_single_elimination_match_labels,
)
from .single_elimination_rendering import (
    build_single_elimination_match_labels,
)


DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG = 'grand_final_reset_skipped'


def build_match_labels(
    matches,
    slots_by_match_id,
    stages_by_id,
) -> dict:
    source_match_id_by_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_slot_id[slot.id] = slot.match_id

    incoming_by_match_id = defaultdict(list)
    for match_id, slots in slots_by_match_id.items():
        for slot in slots:
            if slot.source_match_slot_id is None:
                continue
            source_match_id = source_match_id_by_slot_id.get(slot.source_match_slot_id)
            if source_match_id is None:
                continue
            incoming_by_match_id[match_id].append(
                (source_match_id, slot.source_outcome)
            )

    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    labels_by_match_id = {}
    for stage_id, stage_matches in matches_by_stage_id.items():
        stage = stages_by_id.get(stage_id)
        if stage is None:
            for match in stage_matches:
                labels_by_match_id[match.id] = f'M #{match.match_no}'
            continue

        if stage.type in {
            StageType.double_elimination,
            StageType.double_elimination_double_grand_final,
        }:
            labels_by_match_id.update(
                build_double_elimination_match_labels(
                    stage_matches,
                    incoming_by_match_id,
                )
            )
        elif stage.type == StageType.single_elimination:
            labels_by_match_id.update(
                build_single_elimination_match_labels(
                    stage_matches,
                    incoming_by_match_id,
                )
            )
        elif stage.type in {
            StageType.ffa_single_elimination,
            StageType.ffa_flatout2_single_elimination,
        }:
            labels_by_match_id.update(
                build_ffa_single_elimination_match_labels(stage_matches, stage)
            )
        else:
            for match in stage_matches:
                labels_by_match_id[match.id] = f'M #{match.match_no}'

    return labels_by_match_id


def is_skipped_double_grand_final_result(result) -> bool:
    if result is None or not isinstance(result.score, dict):
        return False

    return bool(result.score.get(DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG))


def build_skipped_double_grand_final_match_ids(
    matches,
    slots_by_match_id,
    results_by_match_id,
    stages_by_id,
) -> set:
    source_match_id_by_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_slot_id[slot.id] = slot.match_id

    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    skipped_match_ids = {
        match.id
        for match in matches
        if is_skipped_double_grand_final_result(results_by_match_id.get(match.id))
    }

    for stage_id, stage_matches in matches_by_stage_id.items():
        stage = stages_by_id.get(stage_id)
        if (
            stage is None
            or stage.type != StageType.double_elimination_double_grand_final
        ):
            continue

        for match in stage_matches:
            slots = slots_by_match_id.get(match.id, [])
            if len(slots) < 2:
                continue
            if any(slot.source_match_slot_id is None for slot in slots):
                continue

            source_slot_ids = {slot.source_match_slot_id for slot in slots}
            outcomes = {slot.source_outcome.value for slot in slots}
            if (
                len(source_slot_ids) != 1
                or outcomes != {'winner', 'loser'}
            ):
                continue

            source_slot_id = next(iter(source_slot_ids))
            source_match_id = source_match_id_by_slot_id.get(source_slot_id)
            if source_match_id is None:
                continue

            source_result = results_by_match_id.get(source_match_id)
            if source_result is None or source_result.winner_slot is None:
                continue

            if source_result.winner_slot == 1:
                skipped_match_ids.add(match.id)

    return skipped_match_ids

def build_slot_scores_by_match_id(
    matches,
    slots_by_match_id,
    results_by_match_id,
) -> dict:
    slot_scores_by_match_id = {}
    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        result = results_by_match_id.get(match.id)
        slot_scores = _parse_slot_scores(slots, result)
        if slot_scores:
            slot_scores_by_match_id[match.id] = slot_scores

    return slot_scores_by_match_id


def _parse_slot_scores(slots, result) -> dict[int, str]:
    if result is None:
        return {}

    if result.score:
        raw_slots = result.score.get('slots')
        if isinstance(raw_slots, dict):
            parsed_scores = {}
            for slot in slots:
                raw_value = raw_slots.get(str(slot.slot_no))
                if raw_value is None:
                    raw_value = raw_slots.get(slot.slot_no)
                if raw_value is None:
                    continue

                normalized = str(raw_value).strip()
                if not normalized:
                    continue

                parsed_scores[slot.slot_no] = normalized

            if parsed_scores:
                return parsed_scores

    display = ''
    if result.score:
        raw_display = result.score.get('display')
        if isinstance(raw_display, str):
            display = raw_display.strip().replace(' ', '')

    if display:
        delimiter = None
        for candidate in [':', '-', '/']:
            if candidate in display:
                delimiter = candidate
                break
        if delimiter is not None:
            parts = display.split(delimiter)
            if len(parts) == len(slots) and all(part.isdigit() for part in parts):
                normalized_parts = list(parts)
                # Keep display aligned with winner slot if a reversed score
                # string was submitted (e.g. winner_slot=1 with "0:1").
                if len(slots) == 2 and result.winner_slot is not None:
                    left = int(parts[0])
                    right = int(parts[1])
                    if left != right:
                        first_slot_no = slots[0].slot_no
                        second_slot_no = slots[1].slot_no
                        winner_has_lower_score = (
                            result.winner_slot == first_slot_no
                            and left < right
                        ) or (
                            result.winner_slot == second_slot_no
                            and right < left
                        )
                        if winner_has_lower_score:
                            normalized_parts = [parts[1], parts[0]]
                return {
                    slot.slot_no: normalized_parts[index]
                    for index, slot in enumerate(slots)
                }

    if result.winner_slot is None:
        return {}

    if len(slots) == 2:
        return {
            slots[0].slot_no: '1' if result.winner_slot == slots[0].slot_no else '0',
            slots[1].slot_no: '1' if result.winner_slot == slots[1].slot_no else '0',
        }

    return {}


def get_or_create_idempotency_key(raw_key: str | None) -> str:
    if raw_key:
        key = raw_key.strip()
        if key:
            return key

    return f'site-{generate_uuid7()}'
