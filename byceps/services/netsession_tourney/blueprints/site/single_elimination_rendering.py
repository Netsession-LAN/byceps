"""
byceps.services.netsession_tourney.blueprints.site.single_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict


def build_single_elimination_match_labels(
    stage_matches,
    incoming_by_match_id,
) -> dict:
    labels_by_match_id = {match.id: f'M #{match.match_no}' for match in stage_matches}
    if not stage_matches:
        return labels_by_match_id

    matches_by_round_no = defaultdict(list)
    for match in stage_matches:
        matches_by_round_no[match.round_no].append(match)

    max_round_no = max(matches_by_round_no.keys())
    final_round_matches = sorted(
        matches_by_round_no[max_round_no], key=lambda match: match.match_no
    )
    consolation_matches = []
    final_matches = []
    for match in final_round_matches:
        incoming = incoming_by_match_id.get(match.id, [])
        if incoming and all(_is_loser_outcome(outcome) for _, outcome in incoming):
            consolation_matches.append(match)
        else:
            final_matches.append(match)

    for index, match in enumerate(sorted(final_matches, key=lambda m: m.match_no), start=1):
        labels_by_match_id[match.id] = (
            'Final' if len(final_matches) == 1 else f'Final #{index}'
        )

    for match in consolation_matches:
        labels_by_match_id[match.id] = 'Consolation Final'

    semi_round_no = max_round_no - 1
    if semi_round_no in matches_by_round_no:
        semi_matches = sorted(
            matches_by_round_no[semi_round_no], key=lambda match: match.match_no
        )
        if len(semi_matches) >= 2:
            for index, match in enumerate(semi_matches, start=1):
                labels_by_match_id[match.id] = f'Semi #{index}'

    return labels_by_match_id


def _is_loser_outcome(outcome) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'
