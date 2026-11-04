"""
byceps.services.netsession_tourney.blueprints.site.ffa_single_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from flask_babel import gettext

from ...models import StageType


def build_ffa_single_elimination_match_labels(stage_matches, stage) -> dict:
    labels_by_match_id = {match.id: f'M #{match.match_no}' for match in stage_matches}
    if not stage_matches:
        return labels_by_match_id

    matches_by_round_no = defaultdict(list)
    for match in stage_matches:
        matches_by_round_no[match.round_no].append(match)

    round_nos = sorted(matches_by_round_no.keys())
    round_count = len(round_nos)
    is_flatout2 = stage.type == StageType.ffa_flatout2_single_elimination
    builder_display_title = str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()
    try:
        total_round_count = int((stage.settings or {}).get('round_count') or 0)
    except (TypeError, ValueError):
        total_round_count = 0

    if is_flatout2:
        return labels_by_match_id

    if builder_display_title:
        for round_no in round_nos:
            round_matches = sorted(
                matches_by_round_no[round_no], key=lambda match: match.match_no
            )
            for index, match in enumerate(round_matches, start=1):
                labels_by_match_id[match.id] = (
                    'Match' if len(round_matches) == 1 else f'Match #{index}'
                )
        return labels_by_match_id

    for round_index, round_no in enumerate(round_nos):
        round_matches = sorted(
            matches_by_round_no[round_no], key=lambda match: match.match_no
        )
        is_final_round = (
            round_no == total_round_count
            if is_flatout2 and total_round_count > 0
            else round_index == round_count - 1
        )
        is_semi_round = (
            not is_flatout2
            and round_index == round_count - 2
            and round_count >= 3
        )

        if is_final_round:
            for index, match in enumerate(round_matches, start=1):
                labels_by_match_id[match.id] = (
                    'Final' if len(round_matches) == 1 else f'Final #{index}'
                )
            continue

        if is_semi_round:
            for index, match in enumerate(round_matches, start=1):
                labels_by_match_id[match.id] = (
                    'Semi-Final'
                    if len(round_matches) == 1
                    else f'Semi-Final #{index}'
                )
            continue

        qualifier_prefix = (
            'Match'
            if is_flatout2
            else 'Quali' if round_count <= 3 else f'Quali {round_index + 1}'
        )
        for index, match in enumerate(round_matches, start=1):
            labels_by_match_id[match.id] = (
                qualifier_prefix
                if len(round_matches) == 1
                else f'{qualifier_prefix} #{index}'
            )

    return labels_by_match_id


def get_ffa_single_elimination_round_title(
    round_index: int,
    round_count: int,
    *,
    stage_type: StageType | None = None,
    round_no: int | None = None,
    total_round_count: int | None = None,
) -> str:
    if stage_type == StageType.ffa_flatout2_single_elimination:
        if (
            total_round_count is not None
            and total_round_count > 0
            and round_no == total_round_count
        ):
            return gettext('Finale')

        return gettext('Runde %(round_no)s', round_no=round_no or round_index + 1)

    if round_count <= 0:
        return gettext('Round')

    if round_index == round_count - 1:
        return 'Final'

    if round_index == round_count - 2 and round_count >= 3:
        return 'Semi-Final'

    return 'Quali' if round_count <= 3 else f'Quali {round_index + 1}'
