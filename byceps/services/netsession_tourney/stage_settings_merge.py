"""
byceps.services.netsession_tourney.stage_settings_merge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Saving the stage form must only replace what the form edits. Settings set
by the stage builder (`builder_*`), the FlatOut 2 setup (`flatout2_*`),
qualification modes and other keys the form does not show are kept.
"""

from __future__ import annotations

from typing import Any


# Settings edited by the stage form (absent from the form = cleared).
FORM_SETTING_KEYS = frozenset(
    [
        'round_count',
        'swiss_threshold',
        'max_players_per_match',
        'group_size',
        'placement_points_rules',
        'points_per_kill',
        'match_duration_minutes',
        'max_matches_per_round',
        'break_between_rounds_minutes',
        'result_report_mode',
    ]
)

# Changes of these change the bracket itself; matches must be regenerated.
STRUCTURAL_SETTING_KEYS = frozenset(
    ['round_count', 'swiss_threshold', 'max_players_per_match', 'group_size']
)


def merge_stage_settings(
    existing: dict[str, Any] | None,
    form_settings: dict[str, Any],
    *,
    type_changed: bool,
) -> dict[str, Any]:
    merged = {
        key: value
        for key, value in (existing or {}).items()
        if key not in FORM_SETTING_KEYS
        and not (type_changed and key.startswith('flatout2_'))
    }
    merged.update(form_settings)
    return merged


def is_structural_change(
    existing: dict[str, Any] | None,
    merged: dict[str, Any],
    *,
    type_changed: bool,
) -> bool:
    existing = existing or {}
    return type_changed or any(
        existing.get(key) != merged.get(key) for key in STRUCTURAL_SETTING_KEYS
    )
