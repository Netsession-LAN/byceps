"""Netsession: FlatOut 2 stages without matches yet show placeholders.

The placeholder builders were called but never imported (NameError).
"""

from types import SimpleNamespace

from byceps.services.netsession_tourney.blueprints.site import stage_render_helpers
from byceps.services.netsession_tourney.models import StageType


def _flatout2_stage_without_plan():
    return SimpleNamespace(
        id='s', type=StageType.ffa_flatout2_single_elimination, settings={}
    )


def test_bracket_of_empty_flatout2_stage_does_not_fail():
    sections = stage_render_helpers._build_stage_public_bracket_sections(
        _flatout2_stage_without_plan(), [], {}, {}, {}, {}, {}
    )

    assert sections == []


def test_match_overview_of_empty_flatout2_stage_does_not_fail():
    sections = stage_render_helpers._build_stage_public_match_sections(
        _flatout2_stage_without_plan(), [], {}, {}, {}, {}, {}, {}, set(), {}
    )

    assert sections == []
