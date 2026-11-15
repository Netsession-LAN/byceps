"""
byceps.services.netsession_tourney.blueprints.api.match_extras
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-match facts the website derives from the bracket structure: round
label, bracket side (upper/lower/grand final), skipped grand final reset,
where winner and loser go next, and which empty slots are byes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ...models import MatchState, SourceOutcome
from ..site.match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
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
    match_id_by_slot_id = {
        slot.id: slot.match_id
        for slots in slots_by_match_id.values()
        for slot in slots
    }
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
    has_explicit_bye = any(
        slot.participant_id is None
        and slot.id not in extras.source_match_id_by_slot_id
        for slot in slots
    ) and any(slot.participant_id is not None for slot in slots)

    bye_ids = set()
    for slot in slots:
        if slot.participant_id is not None:
            continue
        source_match_id = extras.source_match_id_by_slot_id.get(slot.id)
        if source_match_id is None:
            if has_explicit_bye:
                bye_ids.add(slot.id)
            continue
        source_match = extras.matches_by_id.get(source_match_id)
        if (
            source_match is not None
            and source_match.state == MatchState.completed
        ):
            bye_ids.add(slot.id)
    return bye_ids


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


def group_by_stage(matches) -> dict:
    by_stage = defaultdict(list)
    for match in matches:
        by_stage[match.stage_id].append(match)
    return by_stage


def build_advancing_ids_by_match_id(ranking) -> dict:
    """For completed matches of FFA stages: the participants that play in a
    later round or stage. Other matches are left out (no such notion)."""
    order_by_stage_id = {stage.id: stage.order_no for stage in ranking.stages}
    ffa_stage_ids = {
        stage.id
        for stage in ranking.stages
        if stage.type.value.startswith('ffa')
    }

    def position(match) -> tuple:
        return (order_by_stage_id.get(match.stage_id, 0), match.round_no)

    def participant_ids(match) -> set:
        return {
            slot.participant_id
            for slot in ranking.slots_by_match_id.get(match.id, [])
            if slot.participant_id is not None
        }

    advancing = {}
    for match in ranking.matches:
        if match.stage_id not in ffa_stage_ids:
            continue
        if match.state != MatchState.completed:
            continue
        later_ids = set().union(
            *(
                participant_ids(other)
                for other in ranking.matches
                if position(other) > position(match)
            )
        )
        advancing[match.id] = participant_ids(match) & later_ids
    return advancing
