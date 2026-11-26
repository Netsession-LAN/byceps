"""
byceps.services.netsession_tourney.blueprints.site.match_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from byceps.services.netsession_tourney.models import StageType
from byceps.util.uuid import generate_uuid7

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


def _build_source_match_id_by_slot_id(slots_by_match_id) -> dict:
    source_match_id_by_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_slot_id[slot.id] = slot.match_id
    return source_match_id_by_slot_id


def _build_incoming_by_match_id(
    slots_by_match_id, source_match_id_by_slot_id
) -> dict:
    incoming_by_match_id = defaultdict(list)
    for match_id, slots in slots_by_match_id.items():
        for slot in slots:
            if slot.source_match_slot_id is None:
                continue
            source_match_id = source_match_id_by_slot_id.get(
                slot.source_match_slot_id
            )
            if source_match_id is None:
                continue
            incoming_by_match_id[match_id].append(
                (source_match_id, slot.source_outcome)
            )
    return incoming_by_match_id


def _group_matches_by_stage_id(matches) -> dict:
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)
    return matches_by_stage_id


def _build_default_match_labels(stage_matches) -> dict:
    return {match.id: f'M #{match.match_no}' for match in stage_matches}


def _build_stage_match_labels(
    stage, stage_matches, incoming_by_match_id
) -> dict:
    if stage is None:
        return _build_default_match_labels(stage_matches)

    if stage.type in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return build_double_elimination_match_labels(
            stage_matches,
            incoming_by_match_id,
        )

    if stage.type == StageType.single_elimination:
        return build_single_elimination_match_labels(
            stage_matches,
            incoming_by_match_id,
        )

    if stage.type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        return build_ffa_single_elimination_match_labels(stage_matches, stage)

    return _build_default_match_labels(stage_matches)


def build_match_labels(
    matches,
    slots_by_match_id,
    stages_by_id,
) -> dict:
    source_match_id_by_slot_id = _build_source_match_id_by_slot_id(
        slots_by_match_id
    )
    incoming_by_match_id = _build_incoming_by_match_id(
        slots_by_match_id, source_match_id_by_slot_id
    )
    matches_by_stage_id = _group_matches_by_stage_id(matches)

    labels_by_match_id = {}
    for stage_id, stage_matches in matches_by_stage_id.items():
        stage = stages_by_id.get(stage_id)
        labels_by_match_id.update(
            _build_stage_match_labels(
                stage, stage_matches, incoming_by_match_id
            )
        )

    return labels_by_match_id


def is_skipped_double_grand_final_result(result) -> bool:
    if result is None or not isinstance(result.score, dict):
        return False

    return bool(result.score.get(DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG))


def _is_double_grand_final_stage(stage) -> bool:
    return (
        stage is not None
        and stage.type == StageType.double_elimination_double_grand_final
    )


def _has_sourced_slots_only(slots) -> bool:
    if len(slots) < 2:
        return False

    return not any(slot.source_match_slot_id is None for slot in slots)


def _find_reset_source_slot_id(slots):
    if not _has_sourced_slots_only(slots):
        return None

    source_slot_ids = {slot.source_match_slot_id for slot in slots}
    outcomes = {slot.source_outcome.value for slot in slots}
    if len(source_slot_ids) != 1 or outcomes != {'winner', 'loser'}:
        return None

    return next(iter(source_slot_ids))


def _is_skipped_grand_final_reset_match(
    match,
    slots_by_match_id,
    results_by_match_id,
    source_match_id_by_slot_id,
) -> bool:
    slots = slots_by_match_id.get(match.id, [])
    source_slot_id = _find_reset_source_slot_id(slots)
    if source_slot_id is None:
        return False

    source_match_id = source_match_id_by_slot_id.get(source_slot_id)
    if source_match_id is None:
        return False

    source_result = results_by_match_id.get(source_match_id)
    if source_result is None or source_result.winner_slot is None:
        return False

    return source_result.winner_slot == 1


def _collect_flagged_skipped_match_ids(matches, results_by_match_id) -> set:
    return {
        match.id
        for match in matches
        if is_skipped_double_grand_final_result(
            results_by_match_id.get(match.id)
        )
    }


def build_skipped_double_grand_final_match_ids(
    matches,
    slots_by_match_id,
    results_by_match_id,
    stages_by_id,
) -> set:
    source_match_id_by_slot_id = _build_source_match_id_by_slot_id(
        slots_by_match_id
    )
    matches_by_stage_id = _group_matches_by_stage_id(matches)

    skipped_match_ids = _collect_flagged_skipped_match_ids(
        matches, results_by_match_id
    )

    for stage_id, stage_matches in matches_by_stage_id.items():
        stage = stages_by_id.get(stage_id)
        if not _is_double_grand_final_stage(stage):
            continue

        for match in stage_matches:
            if _is_skipped_grand_final_reset_match(
                match,
                slots_by_match_id,
                results_by_match_id,
                source_match_id_by_slot_id,
            ):
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


def _get_raw_slot_score(raw_slots: dict, slot):
    raw_value = raw_slots.get(str(slot.slot_no))
    if raw_value is None:
        raw_value = raw_slots.get(slot.slot_no)
    return raw_value


def _parse_explicit_slot_scores(slots, score) -> dict[int, str]:
    raw_slots = score.get('slots')
    if not isinstance(raw_slots, dict):
        return {}

    parsed_scores = {}
    for slot in slots:
        raw_value = _get_raw_slot_score(raw_slots, slot)
        if raw_value is None:
            continue

        normalized = str(raw_value).strip()
        if not normalized:
            continue

        parsed_scores[slot.slot_no] = normalized

    return parsed_scores


def _get_normalized_score_display(result) -> str:
    if not result.score:
        return ''

    raw_display = result.score.get('display')
    if not isinstance(raw_display, str):
        return ''

    return raw_display.strip().replace(' ', '')


def _find_score_display_delimiter(display: str) -> str | None:
    for candidate in [':', '-', '/']:
        if candidate in display:
            return candidate
    return None


def _split_score_display(display: str, slot_count: int) -> list[str] | None:
    delimiter = _find_score_display_delimiter(display)
    if delimiter is None:
        return None

    parts = display.split(delimiter)
    if len(parts) != slot_count or not all(part.isdigit() for part in parts):
        return None

    return parts


def _winner_has_lower_score(winner_slot, slots, left: int, right: int) -> bool:
    return (winner_slot == slots[0].slot_no and left < right) or (
        winner_slot == slots[1].slot_no and right < left
    )


def _align_score_parts_with_winner(slots, result, parts: list[str]) -> list:
    # Keep display aligned with winner slot if a reversed score
    # string was submitted (e.g. winner_slot=1 with "0:1").
    if len(slots) != 2 or result.winner_slot is None:
        return list(parts)

    left = int(parts[0])
    right = int(parts[1])
    if left == right:
        return list(parts)

    if _winner_has_lower_score(result.winner_slot, slots, left, right):
        return [parts[1], parts[0]]

    return list(parts)


def _parse_display_slot_scores(slots, result) -> dict[int, str] | None:
    display = _get_normalized_score_display(result)
    if not display:
        return None

    parts = _split_score_display(display, len(slots))
    if parts is None:
        return None

    normalized_parts = _align_score_parts_with_winner(slots, result, parts)
    return {
        slot.slot_no: normalized_parts[index]
        for index, slot in enumerate(slots)
    }


def _build_winner_slot_scores(slots, result) -> dict[int, str]:
    if result.winner_slot is None:
        return {}

    if len(slots) != 2:
        return {}

    return {
        slots[0].slot_no: '1'
        if result.winner_slot == slots[0].slot_no
        else '0',
        slots[1].slot_no: '1'
        if result.winner_slot == slots[1].slot_no
        else '0',
    }


def _parse_slot_scores(slots, result) -> dict[int, str]:
    if result is None:
        return {}

    if result.score:
        parsed_scores = _parse_explicit_slot_scores(slots, result.score)
        if parsed_scores:
            return parsed_scores

    display_scores = _parse_display_slot_scores(slots, result)
    if display_scores is not None:
        return display_scores

    return _build_winner_slot_scores(slots, result)


def get_or_create_idempotency_key(raw_key: str | None) -> str:
    if raw_key:
        key = raw_key.strip()
        if key:
            return key

    return f'site-{generate_uuid7()}'
