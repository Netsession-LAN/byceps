"""
byceps.services.netsession_tourney.blueprints.site.routes_match_flatout2_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2 round details and host of the match page.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.flatout2 import get_flatout2_mode_label


def get_flatout2_round_details(match, stage, is_flatout2_match):
    """Return the current host participant ID and the races of a
    FlatOut 2 round.
    """
    if not (is_flatout2_match and stage is not None):
        return '', []

    current_host_participant_id = str(
        (match.settings or {}).get('host_participant_id') or ''
    ).strip()
    return current_host_participant_id, _get_flatout2_round_races(match)


def _get_flatout2_round_races(match) -> list[dict]:
    raw_flatout2_round_races = (match.settings or {}).get(
        'flatout2_races'
    ) or []
    return [
        _with_flatout2_mode_label(race)
        for race in raw_flatout2_round_races
        if isinstance(race, dict)
    ]


def _with_flatout2_mode_label(race: dict) -> dict:
    return {
        **race,
        'mode_label': get_flatout2_mode_label(
            str(race.get('mode') or '').strip() or 'single_race'
        ),
    }


def find_current_host_name(ffa_match_rows, current_host_participant_id):
    return next(
        (
            row['name']
            for row in ffa_match_rows
            if row.get('participant') is not None
            and str(row['participant'].id) == current_host_participant_id
        ),
        None,
    )
