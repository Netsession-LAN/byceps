"""
byceps.services.netsession_tourney.blueprints.site.ffa_single_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from flask_babel import gettext

from byceps.services.netsession_tourney.models import StageType


def _group_matches_by_round_no(stage_matches) -> dict:
    matches_by_round_no = defaultdict(list)
    for match in stage_matches:
        matches_by_round_no[match.round_no].append(match)
    return matches_by_round_no


def _get_builder_display_title(stage) -> str:
    return str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()


def _get_knockout_round_prefix(round_index: int, round_count: int) -> str:
    if round_index == round_count - 1:
        return 'Final'

    if round_index == round_count - 2 and round_count >= 3:
        return 'Semi-Final'

    return 'Quali' if round_count <= 3 else f'Quali {round_index + 1}'


def _label_round_matches(
    labels_by_match_id: dict,
    matches_by_round_no: dict,
    round_no: int,
    prefix: str,
) -> None:
    round_matches = sorted(
        matches_by_round_no[round_no], key=lambda match: match.match_no
    )
    for index, match in enumerate(round_matches, start=1):
        labels_by_match_id[match.id] = (
            prefix if len(round_matches) == 1 else f'{prefix} #{index}'
        )


def _label_builder_rounds(
    labels_by_match_id: dict, matches_by_round_no: dict
) -> None:
    for round_no in sorted(matches_by_round_no.keys()):
        _label_round_matches(
            labels_by_match_id, matches_by_round_no, round_no, 'Match'
        )


def _label_knockout_rounds(
    labels_by_match_id: dict, matches_by_round_no: dict
) -> None:
    round_nos = sorted(matches_by_round_no.keys())
    round_count = len(round_nos)
    for round_index, round_no in enumerate(round_nos):
        prefix = _get_knockout_round_prefix(round_index, round_count)
        _label_round_matches(
            labels_by_match_id, matches_by_round_no, round_no, prefix
        )


def build_ffa_single_elimination_match_labels(stage_matches, stage) -> dict:
    labels_by_match_id = {
        match.id: f'M #{match.match_no}' for match in stage_matches
    }
    if not stage_matches:
        return labels_by_match_id

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return labels_by_match_id

    matches_by_round_no = _group_matches_by_round_no(stage_matches)

    if _get_builder_display_title(stage):
        _label_builder_rounds(labels_by_match_id, matches_by_round_no)
    else:
        _label_knockout_rounds(labels_by_match_id, matches_by_round_no)

    return labels_by_match_id


def _get_flatout2_round_title(
    round_index: int,
    round_no: int | None,
    total_round_count: int | None,
) -> str:
    if (
        total_round_count is not None
        and total_round_count > 0
        and round_no == total_round_count
    ):
        return gettext('Finale')

    return gettext('Runde %(round_no)s', round_no=round_no or round_index + 1)


def get_ffa_single_elimination_round_title(
    round_index: int,
    round_count: int,
    *,
    stage_type: StageType | None = None,
    round_no: int | None = None,
    total_round_count: int | None = None,
) -> str:
    if stage_type == StageType.ffa_flatout2_single_elimination:
        return _get_flatout2_round_title(
            round_index, round_no, total_round_count
        )

    if round_count <= 0:
        return gettext('Round')

    return _get_knockout_round_prefix(round_index, round_count)
