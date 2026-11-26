"""
byceps.services.netsession_tourney.blueprints.site.stage_render_grouping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Group matches by stage and round for the public stage renderings.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict


def group_matches_by_stage_id(matches):
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)
    return matches_by_stage_id


def sort_stage_match_groups(matches_by_stage_id, stages_by_id) -> list:
    """Return the (stage ID, matches) pairs ordered by stage order number
    and name; matches of unknown stages come last.
    """
    return sorted(
        matches_by_stage_id.items(),
        key=lambda item: _get_stage_sort_key(stages_by_id, item[0]),
    )


def _get_stage_sort_key(stages_by_id, stage_id) -> tuple:
    return (
        stages_by_id.get(stage_id).order_no
        if stages_by_id.get(stage_id)
        else 999,
        stages_by_id.get(stage_id).name if stages_by_id.get(stage_id) else '',
    )


def group_matches_by_round(matches):
    grouped = defaultdict(list)
    for match in matches:
        grouped[match.round_no].append(match)

    return [
        {'round_no': round_no, 'matches': grouped[round_no]}
        for round_no in sorted(grouped.keys())
    ]
