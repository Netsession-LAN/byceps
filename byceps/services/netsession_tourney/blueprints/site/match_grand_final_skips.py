"""
byceps.services.netsession_tourney.blueprints.site.match_grand_final_skips
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skipped double elimination grand final reset matches.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from byceps.services.netsession_tourney.models import StageType


DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG = 'grand_final_reset_skipped'


def _build_source_match_id_by_slot_id(slots_by_match_id) -> dict:
    source_match_id_by_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_slot_id[slot.id] = slot.match_id
    return source_match_id_by_slot_id


def _group_matches_by_stage_id(matches) -> dict:
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)
    return matches_by_stage_id


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
