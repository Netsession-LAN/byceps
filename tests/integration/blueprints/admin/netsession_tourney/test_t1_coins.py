"""Admin coin settings of a party and manual coin adjustments."""

import pytest

from byceps.services.netsession_tourney import coin_service

from tests.helpers import generate_token


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'


@pytest.fixture(scope='module')
def coins_url(tourney_party):
    return f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}/coins'


@pytest.fixture(scope='module')
def ticket_category(make_ticket_category, tourney_party):
    return make_ticket_category(tourney_party.id, 'T1 Standard')


@pytest.fixture
def player(make_user):
    return make_user(f'T1Coins{generate_token(4)}')


def _balance(party_id, user) -> int:
    return coin_service.get_user_coin_balance(party_id, user.id).available_coins


def _category_amounts(party_id) -> dict:
    return {
        item.ticket_category_id: item.coin_amount
        for item in coin_service.get_ticket_category_coin_settings_for_party(
            party_id
        )
    }


def test_index_renders(tourney_viewer_client, coins_url, ticket_category):
    response = tourney_viewer_client.get(coins_url)

    assert response.status_code == 200
    assert 'T1 Standard' in response.get_data(as_text=True)


def test_index_without_view_permission_is_forbidden(
    plain_admin_client, coins_url
):
    response = plain_admin_client.get(coins_url)

    assert response.status_code == 403


def test_index_with_unknown_party_returns_404(tourney_admin_client):
    response = tourney_admin_client.get(f'{ADMIN_BASE_URL}/for_party/x/coins')

    assert response.status_code == 404


def test_index_shows_searched_user(
    tourney_admin_client, coins_url, tourney_party, tourney_admin, player
):
    coin_service.adjust_user_coins(
        tourney_party.id, player.id, 7, 'Bonus', tourney_admin
    ).unwrap()

    response = tourney_admin_client.get(
        f'{coins_url}?screen_name={player.screen_name}'
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert player.screen_name in body
    assert 'Bonus' in body


def test_update_settings(
    tourney_admin_client, coins_url, tourney_party, ticket_category, pop_flashes
):
    response = tourney_admin_client.post(
        coins_url,
        data={
            'enabled': 'y',
            'default_coin_amount': '10',
            f'category_coin_{ticket_category.id}': '4',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(f'/for_party/{tourney_party.id}/coins')
    assert pop_flashes(tourney_admin_client) == [
        'Coin-Einstellungen wurden gespeichert.'
    ]
    settings = coin_service.get_coin_settings(tourney_party.id)
    assert settings.enabled
    assert settings.default_coin_amount == 10
    assert _category_amounts(tourney_party.id) == {ticket_category.id: 4}


def test_update_settings_with_empty_category_amount_removes_it(
    tourney_admin_client, coins_url, tourney_party, ticket_category
):
    field_name = f'category_coin_{ticket_category.id}'
    tourney_admin_client.post(
        coins_url, data={'default_coin_amount': '2', field_name: '6'}
    )

    response = tourney_admin_client.post(
        coins_url, data={'default_coin_amount': '2', field_name: ' '}
    )

    assert response.status_code == 302
    assert _category_amounts(tourney_party.id) == {}
    assert not coin_service.get_coin_settings(tourney_party.id).enabled


def test_update_settings_with_invalid_form_is_refused(
    tourney_admin_client, coins_url
):
    response = tourney_admin_client.post(
        coins_url, data={'enabled': 'y', 'default_coin_amount': '-5'}
    )

    assert response.status_code == 200
    assert 'Coin-Einstellungen konnten nicht gespeichert werden.' in (
        response.get_data(as_text=True)
    )


@pytest.mark.parametrize(
    ('raw_amount', 'expected_message_part'),
    [
        ('many', 'ist kein gültiger Coin-Wert eingetragen.'),
        ('-1', 'muss der Coin-Wert 0 oder größer sein.'),
    ],
)
def test_update_settings_with_invalid_category_amount_is_refused(
    tourney_admin_client,
    coins_url,
    tourney_party,
    ticket_category,
    raw_amount,
    expected_message_part,
):
    before = _category_amounts(tourney_party.id)

    response = tourney_admin_client.post(
        coins_url,
        data={
            'default_coin_amount': '3',
            f'category_coin_{ticket_category.id}': raw_amount,
        },
    )

    assert response.status_code == 200
    assert expected_message_part in response.get_data(as_text=True)
    assert _category_amounts(tourney_party.id) == before


def test_update_settings_by_viewer_is_forbidden(
    tourney_viewer_client, coins_url
):
    response = tourney_viewer_client.post(
        coins_url, data={'default_coin_amount': '1'}
    )

    assert response.status_code == 403


def test_adjust_adds_coins(
    tourney_admin_client, coins_url, tourney_party, player, pop_flashes
):
    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={
            'screen_name': f' {player.screen_name} ',
            'plus_amount': '5',
            'note': 'Quiz winner',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/coins?screen_name={player.screen_name}'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'Die Coins für "{player.screen_name}" wurden angepasst.'
    ]
    assert _balance(tourney_party.id, player) == 5
    (entry,) = coin_service.get_recent_coin_ledger_entries_for_user(
        tourney_party.id, player.id
    )
    assert entry.note == 'Quiz winner'


def test_adjust_removes_coins(
    tourney_admin_client, coins_url, tourney_party, tourney_admin, player
):
    coin_service.adjust_user_coins(
        tourney_party.id, player.id, 8, '', tourney_admin
    ).unwrap()

    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': player.screen_name, 'minus_amount': '3'},
    )

    assert response.status_code == 302
    assert _balance(tourney_party.id, player) == 5


def test_adjust_below_zero_is_refused(
    tourney_admin_client, coins_url, tourney_party, player
):
    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': player.screen_name, 'minus_amount': '3'},
    )

    assert response.status_code == 200
    assert 'Das Coin-Guthaben darf nicht negativ werden.' in (
        response.get_data(as_text=True)
    )
    assert _balance(tourney_party.id, player) == 0


@pytest.mark.parametrize(
    ('amounts', 'expected_message'),
    [
        (
            {'plus_amount': '2', 'minus_amount': '1'},
            'Bitte nur Plus-Coins oder Minus-Coins eintragen, nicht beides gleichzeitig.',
        ),
        ({}, 'Bitte einen Wert bei Plus-Coins oder Minus-Coins eintragen.'),
    ],
)
def test_adjust_needs_exactly_one_amount(
    tourney_admin_client,
    coins_url,
    tourney_party,
    player,
    amounts,
    expected_message,
):
    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': player.screen_name, **amounts},
    )

    assert response.status_code == 200
    assert expected_message in response.get_data(as_text=True)
    assert _balance(tourney_party.id, player) == 0


def test_adjust_for_unknown_user_is_refused(tourney_admin_client, coins_url):
    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': 'T1NobodyAtAll', 'plus_amount': '1'},
    )

    assert response.status_code == 200
    assert 'Der angegebene User wurde nicht gefunden.' in (
        response.get_data(as_text=True)
    )


def test_adjust_with_invalid_form_keeps_screen_name(
    tourney_admin_client, coins_url, player
):
    response = tourney_admin_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': player.screen_name, 'plus_amount': 'lots'},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Coin-Anpassung konnte nicht gespeichert werden.' in body
    assert player.screen_name in body


def test_adjust_by_viewer_is_forbidden(
    tourney_viewer_client, coins_url, tourney_party, player
):
    response = tourney_viewer_client.post(
        f'{coins_url}/adjust',
        data={'screen_name': player.screen_name, 'plus_amount': '50'},
    )

    assert response.status_code == 403
    assert _balance(tourney_party.id, player) == 0
