"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.blueprints.admin.routes_create_review_data import (
    _parse_selected_admin_ids,
)


def test_wizard_state_without_admins_selects_none():
    """`admin_user_ids` stored as `None` used to raise a TypeError on the
    review step."""
    assert _parse_selected_admin_ids({'admin_user_ids': None}) == set()
    assert _parse_selected_admin_ids({}) == set()
