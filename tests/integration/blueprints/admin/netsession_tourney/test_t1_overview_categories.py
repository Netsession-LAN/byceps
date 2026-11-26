"""Admin party overview, timetable and tournament categories."""

from uuid import uuid4

import pytest

from byceps.services.netsession_tourney import (
    tournament_category_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'


@pytest.fixture(scope='module')
def party_url(tourney_party):
    return f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}'


@pytest.fixture(scope='module')
def tournament(tourney_party, tourney_admin):
    return tournament_service.create_tournament(
        tourney_party.id,
        't1-overview-cup',
        'T1 Overview Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        tourney_admin,
    ).unwrap()


def _category_titles(party_id) -> list[str]:
    return [
        category.title
        for category in tournament_category_service.get_tournament_categories_for_party(
            party_id
        )
    ]


def test_index_lists_tournaments_of_party(
    tourney_admin_client, party_url, tournament
):
    response = tourney_admin_client.get(party_url)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'T1 Overview Cup' in body


def test_index_with_unknown_party_returns_404(tourney_admin_client):
    response = tourney_admin_client.get(f'{ADMIN_BASE_URL}/for_party/nope')

    assert response.status_code == 404


def test_index_without_view_permission_is_forbidden(
    plain_admin_client, party_url
):
    response = plain_admin_client.get(party_url)

    assert response.status_code == 403


def test_viewer_may_open_index(tourney_viewer_client, party_url):
    response = tourney_viewer_client.get(party_url)

    assert response.status_code == 200


def test_timetable_renders(tourney_admin_client, party_url, tournament):
    response = tourney_admin_client.get(f'{party_url}/timetable')

    assert response.status_code == 200


def test_timetable_with_selected_day_renders(tourney_admin_client, party_url):
    response = tourney_admin_client.get(f'{party_url}/timetable?day=2014-10-24')

    assert response.status_code == 200


def test_category_index_lists_categories(
    tourney_admin_client, party_url, tourney_party
):
    tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Listed'
    ).unwrap()

    response = tourney_admin_client.get(f'{party_url}/categories')

    assert response.status_code == 200
    assert 'T1 Listed' in response.get_data(as_text=True)


def test_category_create_form_renders(tourney_admin_client, party_url):
    response = tourney_admin_client.get(f'{party_url}/categories/create')

    assert response.status_code == 200


def test_category_create_form_needs_manage_permission(
    tourney_viewer_client, party_url
):
    response = tourney_viewer_client.get(f'{party_url}/categories/create')

    assert response.status_code == 403


def test_category_create(
    tourney_admin_client, party_url, tourney_party, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/categories', data={'title': 'T1 Fun'}
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/ns-tourneys/for_party/{tourney_party.id}/categories'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Kategorie "T1 Fun" wurde erstellt.'
    ]
    assert 'T1 Fun' in _category_titles(tourney_party.id)


def test_category_create_without_title_shows_form_again(
    tourney_admin_client, party_url, tourney_party
):
    before = _category_titles(tourney_party.id)

    response = tourney_admin_client.post(
        f'{party_url}/categories', data={'title': ''}
    )

    assert response.status_code == 200
    assert _category_titles(tourney_party.id) == before


def test_category_create_with_duplicate_title_is_refused(
    tourney_admin_client, party_url, tourney_party
):
    tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Twice'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{party_url}/categories', data={'title': 'T1 Twice'}
    )

    assert response.status_code == 200
    assert 'Diesen Kategorietitel gibt es bereits.' in response.get_data(
        as_text=True
    )
    assert _category_titles(tourney_party.id).count('T1 Twice') == 1


def test_category_create_by_viewer_is_forbidden(
    tourney_viewer_client, party_url, tourney_party
):
    response = tourney_viewer_client.post(
        f'{party_url}/categories', data={'title': 'T1 Sneaky'}
    )

    assert response.status_code == 403
    assert 'T1 Sneaky' not in _category_titles(tourney_party.id)


def test_category_update_form_shows_title(tourney_admin_client, tourney_party):
    category = tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Before Edit'
    ).unwrap()

    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/categories/{category.id}/update'
    )

    assert response.status_code == 200
    assert 'T1 Before Edit' in response.get_data(as_text=True)


def test_category_update_form_for_unknown_category_returns_404(
    tourney_admin_client,
):
    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/categories/{uuid4()}/update'
    )

    assert response.status_code == 404


def test_category_update(tourney_admin_client, tourney_party, pop_flashes):
    category = tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Old Name'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{category.id}',
        data={'title': 'T1 New Name'},
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/categories'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Kategorie "T1 New Name" wurde aktualisiert.'
    ]
    updated = tournament_category_service.find_tournament_category(category.id)
    assert updated.title == 'T1 New Name'


def test_category_update_with_invalid_form_shows_form_again(
    tourney_admin_client, tourney_party
):
    category = tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Keep Me'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{category.id}',
        data={'title': 'x' * 41},
    )

    assert response.status_code == 200
    updated = tournament_category_service.find_tournament_category(category.id)
    assert updated.title == 'T1 Keep Me'


def test_category_update_to_existing_title_is_refused(
    tourney_admin_client, tourney_party
):
    tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Taken'
    ).unwrap()
    category = tournament_category_service.create_tournament_category(
        tourney_party.id, 'T1 Renamed'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{category.id}',
        data={'title': 'T1 Taken'},
    )

    assert response.status_code == 200
    assert 'Diesen Kategorietitel gibt es bereits.' in response.get_data(
        as_text=True
    )


def test_category_update_of_unknown_category_returns_404(
    tourney_admin_client,
):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{uuid4()}', data={'title': 'T1 Ghost'}
    )

    assert response.status_code == 404


def test_category_move_down_and_up(
    tourney_admin_client, make_party, brand, pop_flashes
):
    party = make_party(brand)
    first = tournament_category_service.create_tournament_category(
        party.id, 'T1 First'
    ).unwrap()
    tournament_category_service.create_tournament_category(
        party.id, 'T1 Second'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{first.id}/down'
    )
    assert response.status_code == 204
    assert pop_flashes(tourney_admin_client) == [
        'Kategorie wurde nach unten verschoben.'
    ]
    assert _category_titles(party.id) == ['T1 Second', 'T1 First']

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{first.id}/up'
    )
    assert response.status_code == 204
    assert pop_flashes(tourney_admin_client) == [
        'Kategorie wurde nach oben verschoben.'
    ]
    assert _category_titles(party.id) == ['T1 First', 'T1 Second']


def test_category_move_beyond_the_ends_is_refused(
    tourney_admin_client, make_party, brand, pop_flashes
):
    party = make_party(brand)
    only = tournament_category_service.create_tournament_category(
        party.id, 'T1 Only'
    ).unwrap()

    tourney_admin_client.post(f'{ADMIN_BASE_URL}/categories/{only.id}/up')
    assert pop_flashes(tourney_admin_client) == [
        'Die Kategorie steht bereits ganz oben.'
    ]

    tourney_admin_client.post(f'{ADMIN_BASE_URL}/categories/{only.id}/down')
    assert pop_flashes(tourney_admin_client) == [
        'Die Kategorie steht bereits ganz unten.'
    ]


def test_category_move_of_unknown_category_returns_404(tourney_admin_client):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/categories/{uuid4()}/up'
    )

    assert response.status_code == 404
