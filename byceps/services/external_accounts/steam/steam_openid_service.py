"""
byceps.services.external_accounts.steam.steam_openid_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sign in through Steam via OpenID 2.0 to obtain the user's Steam ID.

See https://steamcommunity.com/dev

:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from enum import Enum
import re
from typing import Any
from urllib import parse

import httpx

from byceps.util.result import Err, Ok, Result


OPENID_LOGIN_URL = 'https://steamcommunity.com/openid/login'

PLAYER_SUMMARIES_URL = (
    'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/'
)

TIMEOUT_SECONDS = 10

OPENID_NS = 'http://specs.openid.net/auth/2.0'
OPENID_IDENTIFIER_SELECT = 'http://specs.openid.net/auth/2.0/identifier_select'

CLAIMED_ID_PATTERN = re.compile(
    r'https://steamcommunity\.com/openid/id/(?P<steam_id>[0-9]{17})'
)

# Fields that must be covered by the signature of an assertion
REQUIRED_SIGNED_FIELDS = frozenset(
    [
        'op_endpoint',
        'claimed_id',
        'identity',
        'return_to',
        'response_nonce',
        'assoc_handle',
    ]
)


class SteamVerificationError(Enum):
    cancelled = object()
    unreachable = object()
    invalid = object()
    invalid_steam_id = object()


def build_login_url(return_to: str) -> str:
    """Return the URL to sign in at Steam, which then redirects back
    to `return_to`.
    """
    parts = parse.urlsplit(return_to)
    realm = f'{parts.scheme}://{parts.netloc}'

    query_string_data = {
        'openid.ns': OPENID_NS,
        'openid.mode': 'checkid_setup',
        'openid.return_to': return_to,
        'openid.realm': realm,
        'openid.identity': OPENID_IDENTIFIER_SELECT,
        'openid.claimed_id': OPENID_IDENTIFIER_SELECT,
    }
    query_string = parse.urlencode(query_string_data)
    return f'{OPENID_LOGIN_URL}?{query_string}'


def verify_assertion(
    params: dict[str, str], return_to: str
) -> Result[str, SteamVerificationError]:
    """Verify the positive assertion Steam redirected the user back with.

    Return the Steam ID (SteamID64) on success.
    """
    if params.get('openid.mode') != 'id_res':
        return Err(SteamVerificationError.cancelled)

    if not (
        _is_addressed_to_us(params, return_to) and _is_signed_completely(params)
    ):
        return Err(SteamVerificationError.invalid)

    steam_id = parse_steam_id(params.get('openid.claimed_id', ''))
    if steam_id is None:
        return Err(SteamVerificationError.invalid_steam_id)

    return _check_authentication(params).map(lambda _: steam_id)


def _is_addressed_to_us(params: dict[str, str], return_to: str) -> bool:
    """Return `True` if the assertion was issued by Steam for us."""
    return (
        params.get('openid.op_endpoint') == OPENID_LOGIN_URL
        and params.get('openid.return_to') == return_to
    )


def _is_signed_completely(params: dict[str, str]) -> bool:
    """Return `True` if the signature covers all relevant fields."""
    signed_fields = set(params.get('openid.signed', '').split(','))
    return REQUIRED_SIGNED_FIELDS <= signed_fields and (
        params.get('openid.identity') == params.get('openid.claimed_id')
    )


def parse_steam_id(claimed_id: str) -> str | None:
    """Extract the Steam ID (SteamID64) from the claimed identifier."""
    match = CLAIMED_ID_PATTERN.fullmatch(claimed_id)
    if match is None:
        return None

    return match.group('steam_id')


def _check_authentication(
    params: dict[str, str],
) -> Result[None, SteamVerificationError]:
    """Let Steam confirm that it has issued the assertion."""
    # Send back the OpenID fields of the assertion (but not other query
    # string parameters of the return URL).
    data = {
        key: value for key, value in params.items() if key.startswith('openid.')
    }
    data['openid.mode'] = 'check_authentication'

    try:
        response = httpx.post(
            OPENID_LOGIN_URL, data=data, timeout=TIMEOUT_SECONDS
        )
    except httpx.HTTPError:
        return Err(SteamVerificationError.unreachable)

    if not response.is_success:
        return Err(SteamVerificationError.invalid)

    if 'is_valid:true' not in response.text.splitlines():
        return Err(SteamVerificationError.invalid)

    return Ok(None)


def get_persona_name(api_key: str | None, steam_id: str) -> str | None:
    """Return the public name of the Steam account, if available.

    Requires a Steam Web API key.
    """
    if not api_key:
        return None

    try:
        response = httpx.get(
            PLAYER_SUMMARIES_URL,
            params={'key': api_key, 'steamids': steam_id},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        response_data = response.json()
    except httpx.HTTPError, ValueError:
        return None

    return _extract_persona_name(response_data)


def _extract_persona_name(response_data: Any) -> str | None:
    try:
        name = response_data['response']['players'][0]['personaname']
    except KeyError, IndexError, TypeError:
        return None

    if not isinstance(name, str):
        return None

    return name.strip() or None
