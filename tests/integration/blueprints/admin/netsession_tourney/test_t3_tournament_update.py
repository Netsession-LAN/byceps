"""Admin tournament update form."""

from datetime import datetime
import re
from uuid import uuid4

import pytest
from werkzeug.datastructures import MultiDict

from byceps.services.netsession_tourney import (
    tournament_admin_service,
    tournament_queries,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)

from tests.helpers import log_in_user


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]


@pytest.fixture(scope='module')
def tourney_admin(make_admin):
    """A user who may be assigned as admin of a single tournament."""
    user = make_admin({'netsession_tourney.admin'})
    log_in_user(user.id)
    return user


@pytest.fixture(scope='module')
def draft(t3_make_tourney):
    return t3_make_tourney(
        count=2,
        publish=False,
        generate=False,
        starts_at=datetime(2026, 12, 5, 18, 0),
    )


@pytest.fixture(scope='module')
def load_form(t3_client, t3_form_fields):
    def _wrapper(tourney, **overrides):
        page = t3_client.get(tourney.url + '/update')
        assert page.status_code == 200
        data = MultiDict(
            t3_form_fields(
                page.get_data(as_text=True), str(tourney.tournament.id)
            )
        )
        for key, value in overrides.items():
            if value is None:
                data.poplist(key)
            elif isinstance(value, list):
                data.setlist(key, value)
            else:
                data.setlist(key, [value])
        return data

    return _wrapper


def test_saving_the_unchanged_form_keeps_the_times(
    t3_client, t3_make_tourney, load_form
):
    # Times are stored in UTC and shown in the user's time zone
    # (Europe/Berlin, UTC+1 in December). Saving must not shift them.
    tourney = t3_make_tourney(
        count=2,
        publish=False,
        generate=False,
        starts_at=datetime(2026, 12, 5, 18, 0),
    )

    page = t3_client.get(tourney.url + '/update')
    assert 'value="2026-12-05 19:00:00"' in page.get_data(as_text=True)

    for _ in range(2):
        response = t3_client.post(tourney.url, data=load_form(tourney))
        assert response.status_code == 302

    assert tourney.reload().starts_at == datetime(2026, 12, 5, 18, 0)


def test_update_form_shows_the_stored_values(t3_client, draft):
    response = t3_client.get(draft.url + '/update')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'value="{draft.tournament.slug}"' in body
    assert f'value="{draft.tournament.title}"' in body
    assert 'name="starts_at"' in body


def test_update_saves_the_tournament_and_its_admins(
    t3_client, t3_assert_flash, draft, load_form, tourney_admin
):
    data = load_form(
        draft,
        title='Renamed Cup',
        subtitle='Now with subtitle',
        game='Quake',
        starts_at='2026-12-06T20:30',
        admin_user_ids=[str(tourney_admin.id)],
    )

    response = t3_client.post(draft.url, data=data)

    assert response.status_code == 302
    assert response.location.endswith('?tab=overview')
    t3_assert_flash(t3_client, 'success', 'Turnier wurde gespeichert.')
    tournament = draft.reload()
    assert tournament.title == 'Renamed Cup'
    assert tournament.subtitle == 'Now with subtitle'
    assert tournament.game == 'Quake'
    # entered in the user's time zone (Europe/Berlin), stored in UTC
    assert tournament.starts_at == datetime(2026, 12, 6, 19, 30)
    assert tournament_admin_service.get_tournament_admin_user_ids(
        draft.tournament.id
    ) == {tourney_admin.id}

    page = t3_client.get(draft.url + '/update').get_data(as_text=True)
    assert re.search(
        rf'value="{tourney_admin.id}"\s+data-label="[^"]*"\s+checked', page
    )


def test_changing_the_mode_drops_the_stages(
    t3_client, t3_flashes, t3_make_tourney, load_form
):
    tourney = t3_make_tourney(count=0, publish=False, generate=False)

    response = t3_client.post(
        tourney.url, data=load_form(tourney, mode=TournamentMode.ffa.value)
    )

    assert response.status_code == 302
    flashes = t3_flashes(t3_client)
    assert ('success', 'Turnier wurde gespeichert.') in flashes
    assert (
        'success',
        'Modus geändert, alte Phasen wurden gelöscht.',
    ) in flashes
    assert tourney.reload().mode == TournamentMode.ffa
    assert (
        tournament_queries.get_stages_for_tournament(
            tourney.party.id, tourney.tournament.id
        )
        == []
    )


def test_changing_the_registration_mode(
    t3_client, t3_flashes, t3_make_tourney, load_form
):
    tourney = t3_make_tourney(count=0, publish=False, generate=False)
    data = load_form(
        tourney,
        registration_mode=RegistrationMode.team_captain_managed.value,
        team_size='3',
        substitute_count='1',
    )

    response = t3_client.post(tourney.url, data=data)

    assert response.status_code == 302
    assert ('success', 'Anmeldemodus wurde geändert.') in t3_flashes(t3_client)
    tournament = tourney.reload()
    assert tournament.registration_mode == RegistrationMode.team_captain_managed
    assert tournament.team_size == 3
    assert tournament.substitute_count == 1


@pytest.mark.parametrize(
    ('overrides', 'error'),
    [
        ({'title': ''}, 'form-errors'),
        ({'coin_cost': '-5'}, 'form-errors'),
        ({'mode': 'chess'}, 'form-errors'),
    ],
)
def test_invalid_input_shows_the_form_again(
    t3_client, draft, load_form, overrides, error
):
    title_before = draft.reload().title

    response = t3_client.post(draft.url, data=load_form(draft, **overrides))

    assert response.status_code == 200
    assert error in response.get_data(as_text=True)
    assert draft.reload().title == title_before


def test_sponsored_tournament_needs_a_sponsor_logo(t3_client, draft, load_form):
    data = load_form(draft, title='Sponsored', is_sponsored='y')

    response = t3_client.post(draft.url, data=data)

    # The form is shown again, the flash message right on it.
    assert response.status_code == 200
    assert 'Bitte ein Sponsor-Logo auswählen.' in response.get_data(
        as_text=True
    )
    assert draft.reload().title != 'Sponsored'


def test_mode_of_live_tournament_cannot_change(
    t3_client, t3_make_tourney, load_form
):
    tourney = t3_make_tourney(count=2, generate=False)

    response = t3_client.post(
        tourney.url, data=load_form(tourney, mode=TournamentMode.ffa.value)
    )

    assert response.status_code == 200
    assert 'Der Turniermodus lässt sich nur im Entwurf ändern.' in (
        response.get_data(as_text=True)
    )
    assert tourney.reload().mode == TournamentMode.duel


def test_update_needs_a_category(t3_client, t3_assert_flash, make_party, brand):
    party = make_party(brand)
    base = (
        'http://admin.acmecon.test/ns-tourneys'
        f'/for_party/{party.id}/tournaments/{uuid4()}'
    )

    for method in ('get', 'post'):
        url = base + '/update' if method == 'get' else base
        response = t3_client.open(url, method=method.upper())
        assert response.status_code == 302
        assert response.location.endswith(f'/for_party/{party.id}/categories')
        t3_assert_flash(
            t3_client,
            'danger',
            'Es existieren noch keine Kategorien. '
            'Bitte zuerst eine Kategorie anlegen.',
        )


def test_update_of_unknown_tournament(t3_client, draft):
    base = (
        'http://admin.acmecon.test/ns-tourneys'
        f'/for_party/{draft.party.id}/tournaments/{uuid4()}'
    )

    assert t3_client.get(base + '/update').status_code == 404
    assert t3_client.post(base, data={'title': 'X'}).status_code == 404
