"""
byceps.services.netsession_tourney.blueprints.site.stage_render_team_history_scores
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Score cells of the team history rows.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.score_parsing import (
    get_ffa_points_per_kill,
)

from .round_based_public_rendering import _get_score_display
from .stage_render_ffa_match_details import (
    _get_ffa_placement_by_slot_no,
    get_ffa_points_by_slot_no,
    get_slot_keyed_value,
    parse_score_int,
)


def _get_ffa_scores(stage, result, slots, own_slot):
    """Return placement, points and total points (including kill points)."""
    placement = _get_ffa_placement_by_slot_no(result, slots).get(
        own_slot.slot_no
    )
    points = get_ffa_points_by_slot_no(result, slots).get(own_slot.slot_no, 0)
    raw_kills = get_slot_keyed_value(
        _get_raw_score_slots(result), own_slot.slot_no
    )
    kills = parse_score_int(raw_kills)
    points_per_kill = get_ffa_points_per_kill(
        stage.settings if stage is not None else {}
    )
    total_points = points + (kills * points_per_kill)
    return placement, points, total_points


def _get_raw_score_slots(result) -> dict:
    raw_score_slots = {}
    if result and isinstance(result.score.get('slots'), dict):
        raw_score_slots = result.score.get('slots')
    return raw_score_slots


def _get_score_side(result, index: int) -> str | None:
    score_display = _get_score_display(result)
    if score_display == '-' or ':' not in score_display:
        return None

    parts = score_display.split(':', 1)
    if len(parts) != 2:
        return None

    return parts[index].strip()
