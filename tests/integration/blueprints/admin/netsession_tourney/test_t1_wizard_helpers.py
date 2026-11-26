"""Helpers of the creation and stage builder wizards that the wizard
pages only reach in rare cases.
"""

from uuid import uuid4

from flask import session
import pytest

from byceps.services.netsession_tourney.blueprints.admin.route_config import (
    STAGE_BUILDER_WIZARD_SESSION_KEY,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_review_data import (
    get_selected_admin_users,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    clear_stage_builder_wizard_state,
    get_stage_builder_wizard_state,
    parse_admin_user_ids,
    parse_category_id,
    set_stage_builder_wizard_state,
    slugify_tournament_title,
    update_form_with_categories,
)

from .t1_wizard_steps import create_wizard_party


@pytest.fixture
def request_context(tourney_admin_app):
    with tourney_admin_app.test_request_context():
        yield


@pytest.mark.parametrize('raw_category_id', [None, '', 'not-a-uuid'])
def test_parse_category_id_rejects_invalid_values(raw_category_id):
    assert parse_category_id(raw_category_id) is None


def test_parse_category_id_accepts_uuid():
    category_id = uuid4()

    assert parse_category_id(str(category_id)) == category_id


def test_parse_admin_user_ids_keeps_only_available_valid_ids():
    valid_id = str(uuid4())
    available = {valid_id, 'broken'}

    selected = parse_admin_user_ids(
        [valid_id, 'broken', str(uuid4())], available
    )

    assert {str(user_id) for user_id in selected} == {valid_id}
    assert parse_admin_user_ids(None, available) == set()


def test_slugify_tournament_title():
    assert slugify_tournament_title('  Größte LAN-Party 2026! ') == (
        'grote-lan-party-2026'
    )
    assert len(slugify_tournament_title('x' * 100)) == 60


def test_selected_admin_users_skip_empty_and_invalid_ids(
    request_context, tourney_admin
):
    state = {'admin_user_ids': ['', 'not-a-uuid', str(tourney_admin.id)]}

    users = get_selected_admin_users(state)

    assert [user.id for user in users] == [tourney_admin.id]


def test_update_form_with_categories(request_context, make_party, brand):
    wizard_party = create_wizard_party(make_party, brand)
    category_id = wizard_party.category.id

    form = update_form_with_categories(
        wizard_party.party.id, category_id=category_id
    )

    assert form.category_id.data == str(category_id)
    assert form.category_id.choices == [(str(category_id), 'T1 Main')]


def test_update_form_with_categories_keeps_erroneous_form(
    request_context, make_party, brand
):
    wizard_party = create_wizard_party(make_party, brand)
    erroneous_form = update_form_with_categories(
        wizard_party.party.id, category_id=wizard_party.category.id
    )
    erroneous_form.category_id.data = 'chosen-by-user'

    form = update_form_with_categories(
        wizard_party.party.id,
        category_id=wizard_party.category.id,
        erroneous_form=erroneous_form,
    )

    assert form is erroneous_form
    assert form.category_id.data == 'chosen-by-user'


def test_stage_builder_state_is_kept_per_tournament(request_context):
    set_stage_builder_wizard_state('party-1', 'tournament-a', {'step': 'main'})
    set_stage_builder_wizard_state('party-1', 'tournament-b', {'step': 'x'})

    clear_stage_builder_wizard_state('party-1', 'tournament-b')

    assert get_stage_builder_wizard_state('party-1', 'tournament-a') == {
        'step': 'main'
    }
    assert get_stage_builder_wizard_state('party-1', 'tournament-b') == {}

    clear_stage_builder_wizard_state('party-1', 'tournament-a')

    assert session[STAGE_BUILDER_WIZARD_SESSION_KEY] == {}


@pytest.mark.parametrize(
    'stored_states',
    [
        {'party-1': 'garbage'},
        {'party-1': {'tournament-a': 'garbage'}},
    ],
)
def test_stage_builder_state_ignores_broken_session_data(
    request_context, stored_states
):
    session[STAGE_BUILDER_WIZARD_SESSION_KEY] = stored_states

    assert get_stage_builder_wizard_state('party-1', 'tournament-a') == {}
