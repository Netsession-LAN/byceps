"""
byceps.services.netsession_tourney.blueprints.site.round_robin_group_assignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Derive the groups of a round robin groups stage from who plays whom.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""


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


def _participant_ids(row, slots_by_match_id) -> list:
    slots = slots_by_match_id.get(row['match'].id, [])
    return [slot.participant_id for slot in slots if slot.participant_id]
