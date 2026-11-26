"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from byceps.services.external_accounts.steam import steam_openid_service
from byceps.services.external_accounts.steam.steam_openid_service import (
    SteamVerificationError,
)
from byceps.util.result import Err, Ok


STEAM_ID = '76561197960287930'

FULL_WIDTH_DIGITS = str.maketrans('0123456789', '０１２３４５６７８９')

RETURN_TO = (
    'https://www.acmecon.test/connected_external_accounts/steam/connect/verify'
)


SIGNED = (
    'signed,op_endpoint,claimed_id,identity,return_to,response_nonce,'
    'assoc_handle'
)


def build_assertion(**overrides: str) -> dict[str, str]:
    params = {
        'openid.ns': 'http://specs.openid.net/auth/2.0',
        'openid.mode': 'id_res',
        'openid.op_endpoint': 'https://steamcommunity.com/openid/login',
        'openid.claimed_id': f'https://steamcommunity.com/openid/id/{STEAM_ID}',
        'openid.identity': f'https://steamcommunity.com/openid/id/{STEAM_ID}',
        'openid.return_to': RETURN_TO,
        'openid.response_nonce': '2026-11-26T12:00:00Zabcdef',
        'openid.assoc_handle': '1234567890',
        'openid.signed': SIGNED,
        'openid.sig': 'c2lnbmF0dXJl',
    }
    params.update(overrides)
    return params


@pytest.fixture
def check_authentication(respx_mock):
    return respx_mock.post(steam_openid_service.OPENID_LOGIN_URL)


@pytest.fixture
def player_summaries(respx_mock):
    return respx_mock.get(steam_openid_service.PLAYER_SUMMARIES_URL)


def test_build_login_url():
    url = steam_openid_service.build_login_url(RETURN_TO)

    parts = urlsplit(url)
    assert f'{parts.scheme}://{parts.netloc}{parts.path}' == (
        'https://steamcommunity.com/openid/login'
    )
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert params == {
        'openid.ns': 'http://specs.openid.net/auth/2.0',
        'openid.mode': 'checkid_setup',
        'openid.return_to': RETURN_TO,
        'openid.realm': 'https://www.acmecon.test',
        'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
        'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
    }


@pytest.mark.parametrize(
    ('claimed_id', 'expected'),
    [
        (f'https://steamcommunity.com/openid/id/{STEAM_ID}', STEAM_ID),
        (f'http://steamcommunity.com/openid/id/{STEAM_ID}', None),
        (f'https://steamcommunity.com/openid/id/{STEAM_ID}/', None),
        (f'https://evil.example/openid/id/{STEAM_ID}', None),
        (f'https://steamcommunity.com.evil.example/openid/id/{STEAM_ID}', None),
        ('https://steamcommunity.com/openid/id/12345', None),
        ('https://steamcommunity.com/openid/id/7656119796028793x', None),
        # Unicode digits other than ASCII (here: full-width)
        (
            'https://steamcommunity.com/openid/id/'
            + STEAM_ID.translate(FULL_WIDTH_DIGITS),
            None,
        ),
        ('', None),
    ],
)
def test_parse_steam_id(claimed_id, expected):
    assert steam_openid_service.parse_steam_id(claimed_id) == expected


def test_verify_assertion_succeeds(check_authentication):
    check_authentication.respond(
        text='ns:http://specs.openid.net/auth/2.0\nis_valid:true\n'
    )
    params = build_assertion()

    actual = steam_openid_service.verify_assertion(
        params | {'state': 'not-for-steam'}, RETURN_TO
    )

    assert actual == Ok(STEAM_ID)

    # The OpenID fields are sent back unchanged, except for the mode.
    content = check_authentication.calls.last.request.content.decode()
    sent_data = {key: values[0] for key, values in parse_qs(content).items()}
    assert sent_data == params | {'openid.mode': 'check_authentication'}


@pytest.mark.parametrize(
    'params',
    [
        {},
        build_assertion(**{'openid.mode': 'cancel'}),
    ],
)
def test_verify_assertion_cancelled(check_authentication, params):
    actual = steam_openid_service.verify_assertion(params, RETURN_TO)

    assert actual == Err(SteamVerificationError.cancelled)
    assert check_authentication.call_count == 0


@pytest.mark.parametrize(
    'overrides',
    [
        {'openid.op_endpoint': 'https://evil.example/openid/login'},
        {'openid.return_to': 'https://evil.example/steam/verify'},
        {'openid.identity': 'https://steamcommunity.com/openid/id/123'},
        {'openid.signed': 'signed,op_endpoint,claimed_id,identity,return_to'},
        {'openid.signed': SIGNED.replace(',return_to', '')},
        {'openid.signed': ''},
    ],
)
def test_verify_assertion_rejects_assertion_for_others(
    check_authentication, overrides
):
    params = build_assertion(**overrides)

    actual = steam_openid_service.verify_assertion(params, RETURN_TO)

    assert actual == Err(SteamVerificationError.invalid)
    assert check_authentication.call_count == 0


def test_verify_assertion_rejects_invalid_steam_id(check_authentication):
    claimed_id = 'https://steamcommunity.com/openid/id/abc'
    params = build_assertion(
        **{'openid.claimed_id': claimed_id, 'openid.identity': claimed_id}
    )

    actual = steam_openid_service.verify_assertion(params, RETURN_TO)

    assert actual == Err(SteamVerificationError.invalid_steam_id)
    assert check_authentication.call_count == 0


@pytest.mark.parametrize(
    ('status_code', 'text'),
    [
        (200, 'ns:http://specs.openid.net/auth/2.0\nis_valid:false\n'),
        (200, 'ns:http://specs.openid.net/auth/2.0\nnot_is_valid:true\n'),
        (200, ''),
        (500, 'is_valid:true'),
        (302, ''),
    ],
)
def test_verify_assertion_rejects_unconfirmed_assertion(
    check_authentication, status_code, text
):
    check_authentication.respond(status_code, text=text)

    actual = steam_openid_service.verify_assertion(build_assertion(), RETURN_TO)

    assert actual == Err(SteamVerificationError.invalid)


def test_verify_assertion_when_steam_is_unreachable(check_authentication):
    check_authentication.side_effect = httpx.ConnectError('Steam unreachable')

    actual = steam_openid_service.verify_assertion(build_assertion(), RETURN_TO)

    assert actual == Err(SteamVerificationError.unreachable)


def test_get_persona_name(player_summaries):
    player_summaries.respond(
        json={
            'response': {
                'players': [
                    {'steamid': STEAM_ID, 'personaname': '  Gabe  '},
                ],
            },
        },
    )

    actual = steam_openid_service.get_persona_name('api-key', STEAM_ID)

    assert actual == 'Gabe'

    request = player_summaries.calls.last.request
    assert request.url.params['key'] == 'api-key'
    assert request.url.params['steamids'] == STEAM_ID


@pytest.mark.parametrize(
    'json',
    [
        {'response': {'players': []}},
        {'response': {}},
        {'response': {'players': [{'personaname': '   '}]}},
        {'response': {'players': [{'personaname': 42}]}},
        {'response': {'players': [{}]}},
        ['unexpected'],
        None,
    ],
)
def test_get_persona_name_without_usable_answer(player_summaries, json):
    player_summaries.respond(json=json)

    assert steam_openid_service.get_persona_name('api-key', STEAM_ID) is None


def test_get_persona_name_on_server_error(player_summaries):
    player_summaries.respond(403, text='Forbidden')

    assert steam_openid_service.get_persona_name('api-key', STEAM_ID) is None


def test_get_persona_name_on_invalid_json(player_summaries):
    player_summaries.respond(200, text='<html>Bad Gateway</html>')

    assert steam_openid_service.get_persona_name('api-key', STEAM_ID) is None


def test_get_persona_name_when_steam_is_unreachable(player_summaries):
    player_summaries.side_effect = httpx.ConnectTimeout('Steam unreachable')

    assert steam_openid_service.get_persona_name('api-key', STEAM_ID) is None


@pytest.mark.parametrize('api_key', [None, ''])
def test_get_persona_name_without_api_key(player_summaries, api_key):
    assert steam_openid_service.get_persona_name(api_key, STEAM_ID) is None

    assert player_summaries.call_count == 0
