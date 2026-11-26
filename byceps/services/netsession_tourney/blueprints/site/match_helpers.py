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
from .match_grand_final_skips import (
    _build_source_match_id_by_slot_id,
    _group_matches_by_stage_id,
    build_skipped_double_grand_final_match_ids as build_skipped_double_grand_final_match_ids,
    is_skipped_double_grand_final_result as is_skipped_double_grand_final_result,
)
from .match_score_display import (
    _parse_display_slot_scores,
)
from .single_elimination_rendering import (
    build_single_elimination_match_labels,
)


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
