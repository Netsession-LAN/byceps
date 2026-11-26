"""
byceps.util.turnstile
~~~~~~~~~~~~~~~~~~~~~

Protect forms against bots with Cloudflare Turnstile.

See https://developers.cloudflare.com/turnstile/

:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from typing import Any

from flask import request
import httpx
import structlog

from byceps.byceps_app import get_current_byceps_app
from byceps.config.models import CloudflareTurnstileConfig


log = structlog.get_logger()


VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

TIMEOUT_SECONDS = 3.0

FORM_FIELD_NAME = 'cf-turnstile-response'


def get_enabled_config() -> CloudflareTurnstileConfig | None:
    """Return the configuration if Turnstile is enabled."""
    config = get_current_byceps_app().byceps_config.cloudflare_turnstile

    if not config or not config.enabled:
        return None

    return config


def get_sitekey() -> str | None:
    """Return the public site key if Turnstile is enabled."""
    config = get_enabled_config()
    if not config or not config.sitekey:
        return None

    return config.sitekey


def verify_request(expected_action: str) -> bool:
    """Verify the Turnstile token submitted with the current form.

    Return `True` if Turnstile is disabled.
    """
    config = get_enabled_config()
    if not config:
        return True

    token = request.form.get(FORM_FIELD_NAME, '').strip()

    return verify_token(
        config,
        token,
        remote_ip=request.remote_addr,
        expected_action=expected_action,
    )


def verify_token(
    config: CloudflareTurnstileConfig,
    token: str,
    *,
    remote_ip: str | None = None,
    expected_action: str | None = None,
) -> bool:
    """Ask Cloudflare whether the token is valid.

    If Cloudflare cannot be reached, let the request through (and log
    it) instead of locking everybody out. During such an outage the
    widget cannot load either, so the form arrives without a token.
    Cloudflare is asked even then, so that bots cannot pass by just
    omitting the token while Cloudflare is available.
    """
    if not config.secret_key:
        log.warning('turnstile_secret_key_missing')
        return False

    response_data = _siteverify(config.secret_key, token, remote_ip)
    if response_data is None:
        return True

    return bool(token) and _is_success(response_data, expected_action)


def _is_success(
    response_data: dict[str, Any], expected_action: str | None
) -> bool:
    if not response_data.get('success'):
        return False

    action = response_data.get('action')
    return not (expected_action and action and (action != expected_action))


def _siteverify(
    secret_key: str, token: str, remote_ip: str | None
) -> dict[str, Any] | None:
    """Return Cloudflare's answer, or `None` if there is no usable one."""
    data = {
        'secret': secret_key,
        # An empty response would be rejected without reaching the
        # verification, so send a placeholder.
        'response': token or 'missing',
    }
    if remote_ip:
        data['remoteip'] = remote_ip

    try:
        response = httpx.post(VERIFY_URL, data=data, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        error = type(exc).__name__
    else:
        if isinstance(response_data, dict):
            return response_data
        error = 'unexpected response'

    log.warning(
        'turnstile_cloudflare_unreachable_letting_through',
        error=error,
        remote_ip=remote_ip,
    )
    return None
