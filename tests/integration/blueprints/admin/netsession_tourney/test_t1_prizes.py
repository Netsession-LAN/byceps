"""Admin prizes of a tournament."""

from itertools import count
from uuid import uuid4

import pytest

from byceps.services.netsession_tourney import (
    tournament_prize_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    RuleTemplateBodyFormat,
    TournamentMode,
)

from tests.helpers import generate_token


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'

_prize_positions_counter = count(10)


@pytest.fixture(scope='module')
def party_url(tourney_party):
    return f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}'


def _create_tournament(party_id, admin):
    return tournament_service.create_tournament(
        party_id,
        f't1-prize-{generate_token().lower()}',
        'T1 Prize Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin,
    ).unwrap()


@pytest.fixture(scope='module')
def tournament(tourney_party, tourney_admin):
    return _create_tournament(tourney_party.id, tourney_admin)


def _prize_positions(tournament_id) -> list[int]:
    return [
        prize.position
        for prize in tournament_prize_service.get_tournament_prizes_for_tournament(
            tournament_id
        )
    ]


def test_prize_create_form_renders(tourney_admin_client, party_url, tournament):
    response = tourney_admin_client.get(
        f'{party_url}/tournaments/{tournament.id}/prizes/create'
    )

    assert response.status_code == 200
    assert 'T1 Prize Cup' in response.get_data(as_text=True)


def test_prize_create_form_of_unknown_tournament_returns_404(
    tourney_admin_client, party_url
):
    response = tourney_admin_client.get(
        f'{party_url}/tournaments/{uuid4()}/prizes/create'
    )

    assert response.status_code == 404


def test_prize_create(
    tourney_admin_client, party_url, tourney_party, tourney_admin, pop_flashes
):
    tournament = _create_tournament(tourney_party.id, tourney_admin)

    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes',
        data={'position': '1', 'body_format': 'markdown', 'body': '100 EUR'},
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/tournaments/{tournament.id}?tab=prizes'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Preis für Platz 1 wurde erstellt.'
    ]
    (prize,) = tournament_prize_service.get_tournament_prizes_for_tournament(
        tournament.id
    )
    assert prize.position == 1
    assert prize.body == '100 EUR'


def test_prize_create_with_invalid_position_shows_form_again(
    tourney_admin_client, party_url, tournament
):
    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes',
        data={'position': '0', 'body_format': 'markdown', 'body': 'x'},
    )

    assert response.status_code == 200
    assert 0 not in _prize_positions(tournament.id)


def test_prize_create_for_taken_position_is_refused(
    tourney_admin_client, party_url, tourney_party, tourney_admin
):
    tournament = _create_tournament(tourney_party.id, tourney_admin)
    tournament_prize_service.create_tournament_prize(
        tournament.id, 2, RuleTemplateBodyFormat.markdown, 'Mouse'
    ).unwrap()

    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes',
        data={'position': '2', 'body_format': 'html', 'body': 'Keyboard'},
    )

    assert response.status_code == 200
    assert (
        'Für diese Platzierung gibt es bereits einen Preis.'
        in response.get_data(as_text=True)
    )
    assert _prize_positions(tournament.id) == [2]


def test_prize_create_by_viewer_is_forbidden(
    tourney_viewer_client, party_url, tournament
):
    response = tourney_viewer_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes',
        data={'position': '9', 'body_format': 'markdown', 'body': 'x'},
    )

    assert response.status_code == 403
    assert 9 not in _prize_positions(tournament.id)


@pytest.fixture
def prize(tournament):
    position = next(_prize_positions_counter)
    return tournament_prize_service.create_tournament_prize(
        tournament.id, position, RuleTemplateBodyFormat.html, '<b>Cup</b>'
    ).unwrap()


def test_prize_update_form_shows_values(
    tourney_admin_client, party_url, tournament, prize
):
    response = tourney_admin_client.get(
        f'{party_url}/tournaments/{tournament.id}/prizes/{prize.id}/update'
    )

    assert response.status_code == 200
    assert '&lt;b&gt;Cup&lt;/b&gt;' in response.get_data(as_text=True)


def test_prize_update_form_of_unknown_prize_returns_404(
    tourney_admin_client, party_url, tournament
):
    response = tourney_admin_client.get(
        f'{party_url}/tournaments/{tournament.id}/prizes/{uuid4()}/update'
    )

    assert response.status_code == 404


def test_prize_of_other_tournament_returns_404(
    tourney_admin_client, party_url, tourney_party, tourney_admin, prize
):
    other = _create_tournament(tourney_party.id, tourney_admin)
    prize_url = f'{party_url}/tournaments/{other.id}/prizes/{prize.id}'
    data = {'position': '1', 'body_format': 'html', 'body': 'x'}

    assert tourney_admin_client.get(f'{prize_url}/update').status_code == 404
    assert tourney_admin_client.post(prize_url, data=data).status_code == 404
    assert tourney_admin_client.post(f'{prize_url}/delete').status_code == 404


def test_prize_update(
    tourney_admin_client, party_url, tournament, prize, pop_flashes
):
    new_position = 999

    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes/{prize.id}',
        data={
            'position': str(new_position),
            'body_format': 'markdown',
            'body': 'Headset',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/tournaments/{tournament.id}?tab=prizes'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'Preis für Platz {new_position} wurde aktualisiert.'
    ]
    updated = tournament_prize_service.find_tournament_prize(prize.id)
    assert updated.position == new_position
    assert updated.body_format == RuleTemplateBodyFormat.markdown
    assert updated.body == 'Headset'
    tournament_prize_service.delete_tournament_prize(prize.id)


def test_prize_update_with_invalid_form_shows_form_again(
    tourney_admin_client, party_url, tournament, prize
):
    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes/{prize.id}',
        data={'position': 'first', 'body_format': 'html', 'body': 'x'},
    )

    assert response.status_code == 200
    unchanged = tournament_prize_service.find_tournament_prize(prize.id)
    assert unchanged.position == prize.position


def test_prize_update_to_taken_position_is_refused(
    tourney_admin_client, party_url, tourney_party, tourney_admin
):
    tournament = _create_tournament(tourney_party.id, tourney_admin)
    for position in 1, 2:
        tournament_prize_service.create_tournament_prize(
            tournament.id, position, RuleTemplateBodyFormat.html, 'x'
        ).unwrap()
    second = tournament_prize_service.get_tournament_prizes_for_tournament(
        tournament.id
    )[1]

    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes/{second.id}',
        data={'position': '1', 'body_format': 'html', 'body': 'x'},
    )

    assert response.status_code == 200
    assert (
        'Für diese Platzierung gibt es bereits einen Preis.'
        in response.get_data(as_text=True)
    )


def test_prize_delete(
    tourney_admin_client, party_url, tournament, prize, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{tournament.id}/prizes/{prize.id}/delete'
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/tournaments/{tournament.id}?tab=prizes'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'Preis für Platz {prize.position} wurde gelöscht.'
    ]
    assert tournament_prize_service.find_tournament_prize(prize.id) is None
