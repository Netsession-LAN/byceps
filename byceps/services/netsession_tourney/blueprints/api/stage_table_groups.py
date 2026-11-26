"""
byceps.services.netsession_tourney.blueprints.api.stage_table_groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Splitting the participants of a stage into the groups of its tables.
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.site.round_robin_groups_display import (
    _assign_groups,
    _group_letter,
)
from byceps.services.netsession_tourney.models import StageType


def _split_groups(stage, matches, slots_by_match_id) -> list[tuple]:
    participant_ids = _list_participant_ids(matches, slots_by_match_id)
    if stage.type != StageType.round_robin_groups:
        return [(None, list(dict.fromkeys(participant_ids)), matches)]

    group_index_by_pid = _assign_groups(
        [{'match': match} for match in matches], slots_by_match_id
    )
    group_count = len(set(group_index_by_pid.values()))
    if group_count < 2:
        return [(None, list(group_index_by_pid), matches)]

    return [
        _build_group(index, group_index_by_pid, matches, slots_by_match_id)
        for index in range(group_count)
    ]


def _list_participant_ids(matches, slots_by_match_id) -> list:
    return [
        slot.participant_id
        for match in matches
        for slot in slots_by_match_id.get(match.id, [])
        if slot.participant_id is not None
    ]


def _build_group(
    index: int, group_index_by_pid: dict, matches, slots_by_match_id
) -> tuple:
    pids = [pid for pid, i in group_index_by_pid.items() if i == index]
    group_matches = [
        match
        for match in matches
        if any(
            slot.participant_id in pids
            for slot in slots_by_match_id.get(match.id, [])
        )
    ]
    return ('Gruppe ' + _group_letter(index), pids, group_matches)
