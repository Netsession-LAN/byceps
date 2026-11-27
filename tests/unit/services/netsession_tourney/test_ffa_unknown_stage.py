"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from types import SimpleNamespace

import pytest

from byceps.services.netsession_tourney.blueprints.site.presentation_helpers import (
    get_stage_duration_minutes,
)
from byceps.services.netsession_tourney.blueprints.site.stage_render_ffa_matches import (
    get_stage_builder_display_title,
)


@pytest.mark.parametrize('stage', [None, SimpleNamespace(settings=None)])
def test_ffa_match_overview_helpers_accept_unknown_stages(stage):
    """FFA match overviews used to fail with an AttributeError for a match
    whose stage was unknown or had no settings."""
    assert get_stage_builder_display_title(stage) == ''
    assert get_stage_duration_minutes(stage) is None
