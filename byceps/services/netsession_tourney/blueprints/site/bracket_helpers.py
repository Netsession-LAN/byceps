"""
byceps.services.netsession_tourney.blueprints.site.bracket_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from byceps.services.netsession_tourney.models import MatchState

from .double_elimination_rendering import (
    build_double_elimination_bracket_sections,
    is_double_elimination_bracket,
)


def build_bracket_data(matches, slots_by_match_id, participants_by_id):
    matches_by_id = {match.id: match for match in matches}
    source_match_id_by_source_slot_id = _map_source_match_ids_by_slot_id(
        slots_by_match_id
    )

    rounds = defaultdict(list)
    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        resolved_slots = [
            _resolve_slot(
                slot, participants_by_id, source_match_id_by_source_slot_id
            )
            for slot in slots
        ]
        bracket_slots = _build_bracket_slots(resolved_slots, matches_by_id)
        rounds[match.round_no].append(
            {
                'match': match,
                'slots': bracket_slots,
            }
        )
    return [
        {'round_no': round_no, 'matches': matches_in_round}
        for round_no, matches_in_round in sorted(rounds.items())
    ]


def _map_source_match_ids_by_slot_id(slots_by_match_id) -> dict:
    source_match_id_by_source_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_source_slot_id[slot.id] = slot.match_id
    return source_match_id_by_source_slot_id


def _resolve_slot(
    slot, participants_by_id, source_match_id_by_source_slot_id
) -> dict:
    participant = (
        participants_by_id.get(slot.participant_id)
        if slot.participant_id
        else None
    )
    source_match_id = (
        source_match_id_by_source_slot_id.get(slot.source_match_slot_id)
        if slot.source_match_slot_id
        else None
    )
    return {
        'slot_no': slot.slot_no,
        'participant': participant,
        'source_match_id': source_match_id,
        'source_outcome': slot.source_outcome.value,
    }


def _build_bracket_slots(resolved_slots, matches_by_id) -> list[dict]:
    has_explicit_bye_slot = any(
        _is_empty_unsourced_slot(slot) for slot in resolved_slots
    ) and any(slot['participant'] is not None for slot in resolved_slots)

    return [
        _build_bracket_slot(slot, matches_by_id, has_explicit_bye_slot)
        for slot in resolved_slots
    ]


def _is_empty_unsourced_slot(slot) -> bool:
    return slot['participant'] is None and slot['source_match_id'] is None


def _build_bracket_slot(slot, matches_by_id, has_explicit_bye_slot) -> dict:
    source_match = (
        matches_by_id.get(slot['source_match_id'])
        if slot['source_match_id']
        else None
    )
    is_resolved_empty_source = (
        slot['participant'] is None
        and source_match is not None
        and source_match.state == MatchState.completed
    )
    return {
        'slot_no': slot['slot_no'],
        'participant': slot['participant'],
        'source_match_id': slot['source_match_id'],
        'source_outcome': slot['source_outcome'],
        'is_bye': (
            (has_explicit_bye_slot and _is_empty_unsourced_slot(slot))
            or is_resolved_empty_source
        ),
    }


def build_bracket_sections(bracket, match_labels_by_id):
    if is_double_elimination_bracket(bracket, match_labels_by_id):
        return build_double_elimination_bracket_sections(
            bracket, match_labels_by_id
        )

    return [{'key': 'main', 'title': None, 'rounds': bracket}]
