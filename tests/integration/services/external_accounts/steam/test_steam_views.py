"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from byceps.config.models import SteamConfig
from byceps.services.external_accounts import (
    external_accounts_service,
    signals as external_accounts_signals,
)
from byceps.services.external_accounts.steam import steam_openid_service
from byceps.util.result import Err

from tests.helpers import http_client, log_in_user


SERVER_NAME = 'steam.acmecon.test'

DISABLED_SERVER_NAME = 'steam-disabled.acmecon.test'

BASE_URL = f'http://{SERVER_NAME}/connected_external_accounts/steam'

RETURN_TO = f'{BASE_URL}/connect/verify'


@pytest.fixture(scope='module')
def steam_site_app(make_site_app, site):
    config = SteamConfig(enabled=True, api_key='steam-api-key')
    return make_site_app(SERVER_NAME, site.id, steam=config)


@pytest.fixture(scope='module')
def steam_disabled_site_app(make_site_app, site):
    config = SteamConfig(enabled=False, api_key='steam-api-key')
    return make_site_app(DISABLED_SERVER_NAME, site.id, steam=config)


@pytest.fixture
def user(make_user):
    user = make_user()
    log_in_user(user.id)
    return user


@pytest.fixture
def steam_id() -> str:
    return generate_steam_id()


@pytest.fixture
def check_authentication(respx_mock):
    return respx_mock.post(steam_openid_service.OPENID_LOGIN_URL)


@pytest.fixture
def player_summaries(respx_mock):
    return respx_mock.get(steam_openid_service.PLAYER_SUMMARIES_URL)


@pytest.fixture
def connected_events():
    events = []

    def receiver(sender, *, event):
        events.append(event)

    with external_accounts_signals.external_account_connected.connected_to(
        receiver
    ):
        yield events


def test_connect_redirects_to_steam(steam_site_app, user):
    with http_client(steam_site_app, user_id=user.id) as client:
        response = client.get(f'{BASE_URL}/connect')

    assert response.status_code == 302
    location = urlsplit(response.location)
    assert f'{location.scheme}://{location.netloc}{location.path}' == (
        'https://steamcommunity.com/openid/login'
    )
    params = get_query_params(response.location)
    assert params['openid.mode'] == 'checkid_setup'
    assert params['openid.return_to'].startswith(f'{RETURN_TO}?state=')
    assert params['openid.realm'] == f'http://{SERVER_NAME}'

    state = get_query_params(params['openid.return_to'])['state']
    assert len(state) >= 32


def test_connect_requires_login(steam_site_app):
    with http_client(steam_site_app) as client:
        response = client.get(f'{BASE_URL}/connect')

    assert response.status_code == 302
    assert 'steamcommunity.com' not in response.location


@pytest.mark.parametrize(
    ('app_fixture_name', 'server_name'),
    [
        # no `[steam]` section
        ('site_app', 'www.acmecon.test'),
        # `enabled = false`
        ('steam_disabled_site_app', DISABLED_SERVER_NAME),
    ],
)
@pytest.mark.parametrize('path', ['/connect', '/connect/verify'])
def test_connect_when_disabled(
    request, user, app_fixture_name, server_name, path
):
    app = request.getfixturevalue(app_fixture_name)
    url = f'http://{server_name}/connected_external_accounts/steam{path}'
    with http_client(app, user_id=user.id) as client:
        response = client.get(url)

        assert_redirected_to_settings(response)
        body = get_settings(client, server_name)

    assert 'Connection to Steam currently unavailable.' in body
    assert 'connected_external_accounts/steam' not in body


def test_verify_connects_account(
    steam_site_app,
    user,
    steam_id,
    check_authentication,
    player_summaries,
    connected_events,
):
    check_authentication.respond(text=IS_VALID_TRUE)
    persona_name = f'Player {steam_id}'
    player_summaries.respond(
        json={'response': {'players': [{'personaname': persona_name}]}}
    )

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Steam account connected successfully.' in body
    assert f'<strong>{persona_name}</strong>' in body

    account = find_steam_account(user)
    assert account.external_id == steam_id
    assert account.external_name == persona_name

    assert len(connected_events) == 1
    assert connected_events[0].user.id == user.id
    assert connected_events[0].external_id == steam_id

    # The state is not passed on to Steam.
    content = check_authentication.calls.last.request.content.decode()
    assert 'state' not in parse_qs(content)


def test_verify_uses_steam_id_as_name_without_persona_name(
    steam_site_app, user, steam_id, check_authentication, player_summaries
):
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.side_effect = httpx.ConnectTimeout('Steam unreachable')

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Steam account connected successfully.' in body
    assert find_steam_account(user).external_name == steam_id


def test_verify_rejects_invalid_assertion(
    steam_site_app, user, steam_id, check_authentication, connected_events
):
    check_authentication.respond(text='is_valid:false\n')

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Verification by Steam failed.' in body
    assert find_steam_account(user) is None
    assert connected_events == []


def test_verify_without_connection_attempt(
    steam_site_app, user, steam_id, check_authentication
):
    return_to = f'{RETURN_TO}?state=guessed'
    params = build_assertion(steam_id) | {'openid.return_to': return_to}

    with http_client(steam_site_app, user_id=user.id) as client:
        response = client.get(f'{return_to}&{urlencode(params)}')
        assert_redirected_to_settings(response)
        body = get_settings(client)

    assert 'Verification by Steam failed.' in body
    assert check_authentication.call_count == 0
    assert find_steam_account(user) is None


@pytest.mark.parametrize('state', ['other-state', '', 'näh'])
def test_verify_with_other_state(
    steam_site_app, user, steam_id, check_authentication, state
):
    # E.g. an assertion obtained by someone else, passed on to the user
    other_return_to = f'{RETURN_TO}?{urlencode({"state": state})}'
    params = build_assertion(steam_id) | {'openid.return_to': other_return_to}

    with http_client(steam_site_app, user_id=user.id) as client:
        start_connection(client)
        response = client.get(f'{other_return_to}&{urlencode(params)}')
        assert_redirected_to_settings(response)
        body = get_settings(client)

    assert 'Verification by Steam failed.' in body
    assert check_authentication.call_count == 0
    assert find_steam_account(user) is None


def test_verify_state_cannot_be_reused(
    steam_site_app, user, steam_id, check_authentication, player_summaries
):
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(json={'response': {'players': []}})

    with http_client(steam_site_app, user_id=user.id) as client:
        return_to = start_connection(client)
        params = build_assertion(steam_id) | {'openid.return_to': return_to}
        url = f'{return_to}&{urlencode(params)}'

        client.get(url)
        assert 'Steam account connected successfully.' in get_settings(client)

        client.get(url)
        assert 'Verification by Steam failed.' in get_settings(client)

    assert check_authentication.call_count == 1


def test_verify_when_cancelled(steam_site_app, user, check_authentication):
    body = verify(steam_site_app, user, {'openid.mode': 'cancel'})

    assert 'Sign in through Steam has been cancelled.' in body
    assert check_authentication.call_count == 0
    assert find_steam_account(user) is None


def test_verify_rejects_invalid_steam_id(
    steam_site_app, user, check_authentication
):
    params = build_assertion('1234')  # not a SteamID64

    body = verify(steam_site_app, user, params)

    assert 'Invalid Steam ID.' in body
    assert find_steam_account(user) is None


def test_verify_when_steam_is_unreachable(
    steam_site_app, user, steam_id, check_authentication
):
    check_authentication.side_effect = httpx.ConnectError('Steam unreachable')

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Verification by Steam currently unavailable.' in body
    assert find_steam_account(user) is None


def test_verify_when_already_connected(
    steam_site_app,
    user,
    steam_id,
    check_authentication,
    player_summaries,
    connected_events,
):
    connect_steam_account(user, steam_id)
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(json={'response': {'players': []}})

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Steam account is already connected.' in body
    assert find_steam_account(user).external_id == steam_id
    assert connected_events == []


def test_verify_when_connected_to_other_user(
    steam_site_app,
    user,
    make_user,
    steam_id,
    check_authentication,
    player_summaries,
    connected_events,
):
    other_user = make_user()
    connect_steam_account(other_user, steam_id)
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(json={'response': {'players': []}})

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'This Steam account is already connected to another user.' in body
    assert find_steam_account(user) is None
    assert find_steam_account(other_user).external_id == steam_id
    assert connected_events == []


def test_verify_when_other_steam_account_is_connected(
    steam_site_app, user, steam_id, check_authentication, player_summaries
):
    other_steam_id = generate_steam_id()
    connect_steam_account(user, other_steam_id)
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(json={'response': {'players': []}})

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Another Steam account is already connected.' in body
    assert find_steam_account(user).external_id == other_steam_id


def test_verify_with_persona_name_of_other_account(
    steam_site_app,
    user,
    make_user,
    steam_id,
    check_authentication,
    player_summaries,
):
    # Persona names are not unique on Steam.
    persona_name = f'Player {steam_id}'
    other_user = make_user()
    connect_steam_account(other_user, generate_steam_id(), persona_name)
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(
        json={'response': {'players': [{'personaname': persona_name}]}}
    )

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Steam account connected successfully.' in body
    account = find_steam_account(user)
    assert account.external_id == steam_id
    assert account.external_name == steam_id
    assert find_steam_account(other_user).external_name == persona_name


def test_verify_when_connecting_fails_otherwise(
    steam_site_app,
    user,
    steam_id,
    check_authentication,
    player_summaries,
    connected_events,
    monkeypatch,
):
    monkeypatch.setattr(
        external_accounts_service,
        'connect_external_account',
        lambda *args, **kwargs: Err('Unknown user ID'),
    )
    check_authentication.respond(text=IS_VALID_TRUE)
    player_summaries.respond(json={'response': {'players': []}})

    body = verify(steam_site_app, user, build_assertion(steam_id))

    assert 'Steam account could not be connected.' in body
    assert connected_events == []


def test_settings_show_steam_account(steam_site_app, user, steam_id):
    with http_client(steam_site_app, user_id=user.id) as client:
        body = get_settings(client)
    assert '/connected_external_accounts/steam/connect' in body

    connect_steam_account(user, steam_id, f'Player {steam_id}')

    with http_client(steam_site_app, user_id=user.id) as client:
        body = get_settings(client)
    assert f'<strong>Player {steam_id}</strong>' in body
    assert 'data-action="steam-remove"' in body


def test_settings_hide_steam_when_disabled(site_app, user, steam_id):
    with http_client(site_app, user_id=user.id) as client:
        body = get_settings(client, 'www.acmecon.test')
    assert 'connected_external_accounts/steam' not in body

    # Still show an account connected before, so it can be disconnected.
    connect_steam_account(user, steam_id, f'Player {steam_id}')

    with http_client(site_app, user_id=user.id) as client:
        body = get_settings(client, 'www.acmecon.test')
    assert f'<strong>Player {steam_id}</strong>' in body
    assert 'data-action="steam-remove"' in body
    assert '/connected_external_accounts/steam/connect' not in body


def test_remove_disconnects_account(steam_site_app, user, steam_id):
    connect_steam_account(user, steam_id)

    events = []

    def receiver(sender, *, event):
        events.append(event)

    signal = external_accounts_signals.external_account_disconnected
    with (
        signal.connected_to(receiver),
        http_client(steam_site_app, user_id=user.id) as client,
    ):
        response = client.delete(BASE_URL)

    assert response.status_code == 204
    assert find_steam_account(user) is None
    assert len(events) == 1
    assert events[0].external_id == steam_id


def test_remove_without_account(steam_site_app, user):
    with http_client(steam_site_app, user_id=user.id) as client:
        response = client.delete(BASE_URL)

    assert response.status_code == 204


# helpers


IS_VALID_TRUE = 'ns:http://specs.openid.net/auth/2.0\nis_valid:true\n'


def generate_steam_id() -> str:
    # Must be unique as connections remain in the database.
    return str(76561197960265728 + secrets.randbelow(10**9))


def build_assertion(steam_id: str) -> dict[str, str]:
    claimed_id = f'https://steamcommunity.com/openid/id/{steam_id}'
    return {
        'openid.ns': 'http://specs.openid.net/auth/2.0',
        'openid.mode': 'id_res',
        'openid.op_endpoint': steam_openid_service.OPENID_LOGIN_URL,
        'openid.claimed_id': claimed_id,
        'openid.identity': claimed_id,
        'openid.return_to': RETURN_TO,
        'openid.response_nonce': '2026-11-26T12:00:00Zabcdef',
        'openid.assoc_handle': '1234567890',
        'openid.signed': (
            'signed,op_endpoint,claimed_id,identity,return_to,response_nonce,'
            'assoc_handle'
        ),
        'openid.sig': 'c2lnbmF0dXJl',
    }


def verify(app, user, params: dict[str, str]) -> str:
    """Start a connection attempt, return from Steam with the assertion,
    and return the settings page shown afterwards.
    """
    with http_client(app, user_id=user.id) as client:
        return_to = start_connection(client)
        if 'openid.return_to' in params:
            params = params | {'openid.return_to': return_to}

        response = client.get(f'{return_to}&{urlencode(params)}')

        assert_redirected_to_settings(response)
        return get_settings(client)


def start_connection(client) -> str:
    """Return the URL Steam is told to return to."""
    response = client.get(f'{BASE_URL}/connect')
    return get_query_params(response.location)['openid.return_to']


def get_query_params(url: str) -> dict[str, str]:
    query = urlsplit(url).query
    return {key: values[0] for key, values in parse_qs(query).items()}


def assert_redirected_to_settings(response) -> None:
    assert response.status_code == 302
    assert urlsplit(response.location).path == '/users/me/settings'


def get_settings(client, server_name: str = SERVER_NAME) -> str:
    response = client.get(f'http://{server_name}/users/me/settings')
    assert response.status_code == 200
    return response.get_data(as_text=True)


def connect_steam_account(user, steam_id: str, name: str | None = None):
    external_accounts_service.connect_external_account(
        datetime.utcnow(),
        user.id,
        'steam',
        external_id=steam_id,
        external_name=name or steam_id,
    ).unwrap()


def find_steam_account(user):
    return external_accounts_service.find_connected_external_account_for_user_and_service(
        user.id, 'steam'
    )
