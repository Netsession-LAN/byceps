"""
byceps.services.external_accounts.steam.blueprints.site.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Connector to Steam

:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime
import secrets

from flask import g, redirect, request, session, url_for
from flask_babel import gettext

from byceps.byceps_app import get_current_byceps_app
from byceps.config.models import SteamConfig
from byceps.services.external_accounts import (
    external_accounts_service,
    signals as external_accounts_signals,
)
from byceps.services.external_accounts.steam import steam_openid_service
from byceps.services.external_accounts.steam.steam_openid_service import (
    SteamVerificationError,
)
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import login_required, redirect_to, respond_no_content


blueprint = create_blueprint('connected_external_accounts_steam', __name__)


SERVICE_NAME = 'steam'

# Ties the return from Steam to the connection attempt started by the
# same user (to prevent connecting someone else's Steam account).
STATE_SESSION_KEY = 'connected_external_accounts_steam_state'


@blueprint.get('/connect')
@login_required
def connect():
    """Connect account with Steam via OpenID 2.0."""
    if not _get_enabled_steam_configuration():
        return _unavailable()

    state = secrets.token_urlsafe()
    session[STATE_SESSION_KEY] = state

    login_url = steam_openid_service.build_login_url(_get_return_to_url(state))
    return redirect(login_url)


@blueprint.get('/connect/verify')
@login_required
def connect_verify():
    """Verify the assertion Steam redirected the user back with."""
    config = _get_enabled_steam_configuration()
    if not config:
        return _unavailable()

    state = _pop_matching_state()
    if state is None:
        flash_error(_get_verification_error_message(None))
        return redirect_to('user_settings.view')

    verification_result = steam_openid_service.verify_assertion(
        request.args.to_dict(), _get_return_to_url(state)
    )

    match verification_result:
        case Ok(steam_id):
            _connect_account(config, steam_id)
        case Err(error):
            flash_error(_get_verification_error_message(error))

    return redirect_to('user_settings.view')


def _pop_matching_state() -> str | None:
    """Remove the state from the session and return it, but only if it
    matches the one in the request.
    """
    expected_state = session.pop(STATE_SESSION_KEY, None)
    actual_state = request.args.get('state', '')

    if not expected_state or not secrets.compare_digest(
        actual_state.encode(), expected_state.encode()
    ):
        return None

    return expected_state


def _connect_account(config: SteamConfig, steam_id: str) -> None:
    persona_name = steam_openid_service.get_persona_name(
        config.api_key, steam_id
    )

    if _try_to_connect_account(steam_id, persona_name or steam_id):
        return

    if _flash_connection_conflict(steam_id):
        return

    # The persona name is not unique, but the name of the connection has
    # to be. Fall back to the Steam ID if another account took it.
    if persona_name and _try_to_connect_account(steam_id, steam_id):
        return

    flash_error(gettext('Steam account could not be connected.'))


def _try_to_connect_account(steam_id: str, external_name: str) -> bool:
    now = datetime.utcnow()

    connection_result = external_accounts_service.connect_external_account(
        now,
        g.user.id,
        SERVICE_NAME,
        external_id=steam_id,
        external_name=external_name,
    )

    match connection_result:
        case Ok((_, event)):
            external_accounts_signals.external_account_connected.send(
                None, event=event
            )
            flash_success(gettext('Steam account connected successfully.'))
            return True
        case _:
            return False


def _flash_connection_conflict(steam_id: str) -> bool:
    """Flash a message and return `True` if either the user or the Steam
    account is already connected.
    """
    own_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        g.user.id, SERVICE_NAME
    )

    if own_account is not None:
        if own_account.external_id == steam_id:
            flash_success(gettext('Steam account is already connected.'))
        else:
            flash_error(gettext('Another Steam account is already connected.'))
        return True

    if external_accounts_service.find_connected_external_account_for_service_and_external_id(
        SERVICE_NAME, steam_id
    ):
        flash_error(
            gettext('This Steam account is already connected to another user.')
        )
        return True

    return False


def _get_verification_error_message(
    error: SteamVerificationError | None,
) -> str:
    match error:
        case SteamVerificationError.cancelled:
            return gettext('Sign in through Steam has been cancelled.')
        case SteamVerificationError.unreachable:
            return gettext('Verification by Steam currently unavailable.')
        case SteamVerificationError.invalid_steam_id:
            return gettext('Invalid Steam ID.')
        case _:
            return gettext('Verification by Steam failed.')


@blueprint.delete('')
@login_required
@respond_no_content
def remove():
    """Unlink Steam account."""
    connected_external_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        g.user.id, SERVICE_NAME
    )
    if not connected_external_account:
        return

    disconnection_result = (
        external_accounts_service.disconnect_external_account(
            connected_external_account.id
        )
    )

    event = disconnection_result.unwrap()

    external_accounts_signals.external_account_disconnected.send(
        None, event=event
    )


def _unavailable():
    flash_error(gettext('Connection to Steam currently unavailable.'))
    return redirect_to('user_settings.view')


def _get_return_to_url(state: str) -> str:
    return url_for('.connect_verify', state=state, _external=True)


def _get_enabled_steam_configuration() -> SteamConfig | None:
    config = get_current_byceps_app().byceps_config.steam

    if not config or not config.enabled:
        return None

    return config
