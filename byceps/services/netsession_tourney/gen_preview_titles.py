"""
byceps.services.netsession_tourney.gen_preview_titles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Round display titles for the match generation preview of a stage
(builder title, FlatOut 2 rounds, double elimination brackets).
"""

from __future__ import annotations

from .engines.base import MatchSpec
from .gen_preview_titles_double_elim import (
    _build_double_elimination_generation_preview_round_titles,
)
from .gen_preview_titles_flatout2 import (
    _build_flatout2_generation_preview_round_titles,
)
from .models import (
    Stage,
    StageType,
)


def build_generation_preview_round_titles_by_round_no(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    builder_display_title = _get_builder_display_title(stage)
    if builder_display_title:
        return _build_same_title_for_all_rounds(
            match_specs, builder_display_title
        )

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return _build_flatout2_generation_preview_round_titles(
            stage, match_specs
        )

    if stage.type not in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return {}

    return _build_double_elimination_generation_preview_round_titles(
        match_specs
    )


def _get_builder_display_title(stage: Stage) -> str:
    return str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()


def _build_same_title_for_all_rounds(
    match_specs: list[MatchSpec], title: str
) -> dict[int, str]:
    round_nos = sorted({spec.round_no for spec in match_specs})
    return {round_no: title for round_no in round_nos}
