"""
byceps.services.netsession_tourney.blueprints.site.single_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from .double_elimination_rendering import is_loser_outcome


def _is_consolation_match(match, incoming_by_match_id) -> bool:
    incoming = incoming_by_match_id.get(match.id, [])
    return bool(incoming) and all(
        is_loser_outcome(outcome) for _, outcome in incoming
    )


def _split_final_round_matches(
    final_round_matches,
    incoming_by_match_id,
) -> tuple[list, list]:
    consolation_matches = []
    final_matches = []
    for match in final_round_matches:
        if _is_consolation_match(match, incoming_by_match_id):
            consolation_matches.append(match)
        else:
            final_matches.append(match)
    return consolation_matches, final_matches


def _label_final_round_matches(
    labels_by_match_id: dict,
    final_round_matches,
    incoming_by_match_id,
) -> None:
    consolation_matches, final_matches = _split_final_round_matches(
        final_round_matches, incoming_by_match_id
    )

    for index, match in enumerate(
        sorted(final_matches, key=lambda m: m.match_no), start=1
    ):
        labels_by_match_id[match.id] = (
            'Final' if len(final_matches) == 1 else f'Final #{index}'
        )

    for match in consolation_matches:
        labels_by_match_id[match.id] = 'Consolation Final'


def _label_semi_final_matches(
    labels_by_match_id: dict,
    matches_by_round_no,
    semi_round_no: int,
) -> None:
    if semi_round_no not in matches_by_round_no:
        return

    semi_matches = sorted(
        matches_by_round_no[semi_round_no], key=lambda match: match.match_no
    )
    if len(semi_matches) < 2:
        return

    for index, match in enumerate(semi_matches, start=1):
        labels_by_match_id[match.id] = f'Semi #{index}'


def build_single_elimination_match_labels(
    stage_matches,
    incoming_by_match_id,
) -> dict:
    labels_by_match_id = {
        match.id: f'M #{match.match_no}' for match in stage_matches
    }
    if not stage_matches:
        return labels_by_match_id

    matches_by_round_no = defaultdict(list)
    for match in stage_matches:
        matches_by_round_no[match.round_no].append(match)

    max_round_no = max(matches_by_round_no.keys())
    final_round_matches = sorted(
        matches_by_round_no[max_round_no], key=lambda match: match.match_no
    )
    _label_final_round_matches(
        labels_by_match_id, final_round_matches, incoming_by_match_id
    )
    _label_semi_final_matches(
        labels_by_match_id, matches_by_round_no, max_round_no - 1
    )

    return labels_by_match_id
