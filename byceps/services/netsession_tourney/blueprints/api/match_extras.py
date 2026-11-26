"""
byceps.services.netsession_tourney.blueprints.api.match_extras
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-match facts the website derives from the bracket structure: round
label, bracket side (upper/lower/grand final), skipped grand final reset,
where winner and loser go next, and which empty slots are byes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
)
from byceps.services.netsession_tourney.models import MatchState, SourceOutcome

from .match_extras_advancing import (
    _get_later_participant_ids as _get_later_participant_ids,
    build_advancing_ids_by_match_id as build_advancing_ids_by_match_id,
    group_by_stage as group_by_stage,
)


@dataclass(frozen=True, kw_only=True)
class MatchExtras:
    round_label_by_match_id: dict
    skipped_match_ids: set
    next_match_id_by_match_id: dict = field(default_factory=dict)
    loser_next_match_id_by_match_id: dict = field(default_factory=dict)
    source_match_id_by_slot_id: dict = field(default_factory=dict)
    matches_by_id: dict = field(default_factory=dict)


def build_match_extras(ranking) -> MatchExtras:
    """`ranking` is a `TournamentRanking` (it holds all tournament data)."""
    stages_by_id = {stage.id: stage for stage in ranking.stages}
    slots_by_match_id = ranking.slots_by_match_id
    next_by_match_id, loser_next_by_match_id, source_match_id_by_slot_id = (
        _build_slot_links(slots_by_match_id)
    )

    return MatchExtras(
        round_label_by_match_id=build_match_labels(
            ranking.matches, slots_by_match_id, stages_by_id
        ),
        skipped_match_ids=build_skipped_double_grand_final_match_ids(
            ranking.matches,
            slots_by_match_id,
            ranking.results_by_match_id,
            stages_by_id,
        ),
        next_match_id_by_match_id=next_by_match_id,
        loser_next_match_id_by_match_id=loser_next_by_match_id,
        source_match_id_by_slot_id=source_match_id_by_slot_id,
        matches_by_id={match.id: match for match in ranking.matches},
    )


def _build_slot_links(slots_by_match_id) -> tuple[dict, dict, dict]:
    """Where winners and losers go next, and the source match per slot."""
    match_id_by_slot_id = _build_match_id_by_slot_id(slots_by_match_id)
    next_by_match_id = {}
    loser_next_by_match_id = {}
    source_match_id_by_slot_id = {}
    for match_id, slots in slots_by_match_id.items():
        for slot in slots:
            source_match_id = match_id_by_slot_id.get(slot.source_match_slot_id)
            if source_match_id is None:
                continue
            source_match_id_by_slot_id[slot.id] = source_match_id
            if slot.source_outcome == SourceOutcome.loser:
                loser_next_by_match_id[source_match_id] = match_id
            else:
                next_by_match_id[source_match_id] = match_id

    return next_by_match_id, loser_next_by_match_id, source_match_id_by_slot_id


def _build_match_id_by_slot_id(slots_by_match_id) -> dict:
    return {
        slot.id: slot.match_id
        for slots in slots_by_match_id.values()
        for slot in slots
    }


def describe_match(match, extras: MatchExtras) -> dict:
    label = extras.round_label_by_match_id.get(match.id)
    if label is not None and label.startswith('M #'):
        label = None
    bracket = _bracket_for_label(label)
    return {
        'round_label': label,
        'bracket': bracket,
        'reset': label == 'Double Grand Final'
        if bracket == 'grand_final'
        else None,
        'skipped': match.id in extras.skipped_match_ids,
        'next_match_id': _str(extras.next_match_id_by_match_id.get(match.id)),
        'loser_next_match_id': _str(
            extras.loser_next_match_id_by_match_id.get(match.id)
        ),
    }


def bye_slot_ids(slots, extras: MatchExtras) -> set:
    """Empty slots that will never get a participant (website rule)."""
    has_explicit_bye = _has_explicit_bye(slots, extras)

    bye_ids = set()
    for slot in slots:
        if _is_bye_slot(slot, extras, has_explicit_bye):
            bye_ids.add(slot.id)
    return bye_ids


def _has_explicit_bye(slots, extras: MatchExtras) -> bool:
    return any(
        slot.participant_id is None
        and slot.id not in extras.source_match_id_by_slot_id
        for slot in slots
    ) and any(slot.participant_id is not None for slot in slots)


def _is_bye_slot(slot, extras: MatchExtras, has_explicit_bye: bool) -> bool:
    if slot.participant_id is not None:
        return False
    source_match_id = extras.source_match_id_by_slot_id.get(slot.id)
    if source_match_id is None:
        return has_explicit_bye
    source_match = extras.matches_by_id.get(source_match_id)
    return (
        source_match is not None and source_match.state == MatchState.completed
    )


def _bracket_for_label(label: str | None) -> str | None:
    if label is None:
        return None
    if label.startswith('WB '):
        return 'upper'
    if label.startswith('LB '):
        return 'lower'
    if label.startswith(('Grand Final', 'Double Grand Final')):
        return 'grand_final'
    return None


def _str(value) -> str | None:
    return str(value) if value is not None else None
