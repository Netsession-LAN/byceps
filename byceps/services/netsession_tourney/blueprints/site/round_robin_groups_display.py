"""
byceps.services.netsession_tourney.blueprints.site.round_robin_groups_display
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Split the match overview of a "Round Robin Groups" stage into its groups,
each with its own rounds and ranking table.

The groups are not stored; like the service does for qualifiers, they are
derived from who plays whom: participants that meet (directly or through
others) belong to the same group.
"""

from flask_babel import gettext

from byceps.services.netsession_tourney.models import StageType

from .ranking_helpers import build_ranking_rows


def add_round_robin_groups(
    sections,
    stages_by_id,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
) -> None:
    """Add a `groups` list to every section of a round robin groups stage."""
    for section in sections:
        rows = [row for round in section['rounds'] for row in round['rows']]
        if not _is_round_robin_groups_section(rows, stages_by_id):
            continue

        group_index_by_participant_id = _assign_groups(rows, slots_by_match_id)
        group_count = len(set(group_index_by_participant_id.values()))
        if group_count < 2:
            continue

        section['groups'] = [
            _build_group(
                index,
                section['rounds'],
                group_index_by_participant_id,
                slots_by_match_id,
                results_by_match_id,
                participants_by_id,
            )
            for index in range(group_count)
        ]


def _is_round_robin_groups_section(rows, stages_by_id) -> bool:
    stage = stages_by_id.get(rows[0]['match'].stage_id) if rows else None
    return stage is not None and stage.type == StageType.round_robin_groups


def _assign_groups(rows, slots_by_match_id) -> dict:
    """Return the group index (in order of first match) per participant."""
    parent = {}

    def find(participant_id):
        parent.setdefault(participant_id, participant_id)
        while parent[participant_id] != participant_id:
            participant_id = parent[participant_id]
        return participant_id

    order = []
    for row in sorted(rows, key=lambda row: row['match'].match_no):
        participant_ids = _participant_ids(row, slots_by_match_id)
        order.extend(participant_ids)
        for participant_id in participant_ids[1:]:
            parent[find(participant_id)] = find(participant_ids[0])

    group_index_by_root = {}
    for participant_id in order:
        group_index_by_root.setdefault(
            find(participant_id), len(group_index_by_root)
        )

    return {
        participant_id: group_index_by_root[find(participant_id)]
        for participant_id in order
    }


def _build_group(
    index,
    rounds,
    group_index_by_participant_id,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
) -> dict:
    group_rounds = _select_group_rounds(
        index, rounds, group_index_by_participant_id, slots_by_match_id
    )
    matches = [row['match'] for round in group_rounds for row in round['rows']]
    participants = _select_group_participants(
        index, group_index_by_participant_id, participants_by_id
    )

    return {
        'title': gettext('Gruppe') + ' ' + _group_letter(index),
        'rounds': group_rounds,
        'ranking_rows': build_ranking_rows(
            participants,
            matches,
            {
                match.id: slots_by_match_id.get(match.id, [])
                for match in matches
            },
            results_by_match_id,
            stage_type=StageType.round_robin_groups,
        ),
    }


def _select_group_rounds(
    index, rounds, group_index_by_participant_id, slots_by_match_id
) -> list[dict]:
    def in_group(row) -> bool:
        return any(
            group_index_by_participant_id.get(participant_id) == index
            for participant_id in _participant_ids(row, slots_by_match_id)
        )

    return [
        {**round, 'rows': rows}
        for round in rounds
        if (rows := [row for row in round['rows'] if in_group(row)])
    ]


def _select_group_participants(
    index, group_index_by_participant_id, participants_by_id
) -> list:
    return [
        participants_by_id[participant_id]
        for participant_id, group_index in group_index_by_participant_id.items()
        if group_index == index and participant_id in participants_by_id
    ]


def _participant_ids(row, slots_by_match_id) -> list:
    slots = slots_by_match_id.get(row['match'].id, [])
    return [slot.participant_id for slot in slots if slot.participant_id]


def _group_letter(index: int) -> str:
    letters = ''
    value = index
    while True:
        value, remainder = divmod(value, 26)
        letters = chr(ord('A') + remainder) + letters
        if value == 0:
            return letters
        value -= 1
