"""
byceps.util.turnstile
~~~~~~~~~~~~~~~~~~~~~

Strict Cloudflare Turnstile integration (no legacy fallbacks).
"""

from __future__ import annotations
from typing import Any, Dict, Optional

from flask import current_app, request as flask_request
import httpx
import structlog

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

log = structlog.get_logger()


def _get_cfg_raw() -> Dict[str, Any]:
    """Read the nested Cloudflare Turnstile block as set on app.config."""
    # Injected as `CLOUDFLARE_TURNSTILE` by `byceps.application`. Reading
    # the lowercase key (as before) always yielded `{}`, i.e. "disabled",
    # so every non-empty token was accepted without asking Cloudflare.
    return current_app.config.get("CLOUDFLARE_TURNSTILE") or {}


def get_public_options() -> Dict[str, Any]:
    """Expose only what templates need to render the widget (no secrets)."""
    cfg = _get_cfg_raw()
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "sitekey": cfg.get("sitekey") or "",
    }


def is_enabled() -> bool:
    """Convenience: is Turnstile feature toggled on?"""
    cfg = _get_cfg_raw()
    return bool(cfg.get("enabled", False))


def best_remote_ip(req: Optional[object] = None) -> str:
    """
    Try to determine the original client IP.
    Prefers CF-Connecting-IP, falls back to first X-Forwarded-For, then remote_addr.
    """
    r = req or flask_request
    xff = (r.headers.get("X-Forwarded-For") or "").split(",")
    xff_first = (xff[0].strip() if xff and xff[0].strip() else "")
    return r.headers.get("CF-Connecting-IP") or xff_first or r.remote_addr


def _siteverify(
    secret_key: str, token: str, remoteip: Optional[str], timeout: float
) -> Optional[Dict[str, Any]]:
    """Ask Cloudflare; return its answer, or None if it cannot be reached."""
    data = {"secret": secret_key, "response": token}
    if remoteip:
        data["remoteip"] = remoteip

    try:
        response = httpx.post(VERIFY_URL, data=data, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning(
            "turnstile_cloudflare_unreachable_letting_through",
            error=type(exc).__name__,
            remoteip=remoteip,
        )
        return None


def verify_token(
    token: Optional[str],
    *,
    remoteip: Optional[str] = None,
    timeout: float = 3.0,
    expected_action: Optional[str] = None,
) -> bool:
    """
    Strict server-side verification; requires secret_key.
    Returns True if feature is disabled (do not block flows),
    otherwise only when Cloudflare validates the token (and optional action matches).

    If Cloudflare cannot be reached, the request is let through and logged
    (decision 2026-11-06: an outage must not lock everybody out). A missing
    token (the widget does not load during an outage) is only let through
    if Cloudflare is really unreachable, so bots cannot just omit it.
    """
    cfg = _get_cfg_raw()
    if not bool(cfg.get("enabled", False)):
        return True  # feature off → do not block

    secret_key = cfg.get("secret_key") or ""
    if not secret_key:
        return False

    timeout = float(max(0.5, min(10.0, abs(timeout))))
    payload = _siteverify(secret_key, token or "missing", remoteip, timeout)
    if payload is None:
        return True  # Cloudflare down → let through (logged)

    if not token or not bool(payload.get("success")):
        return False

    if expected_action:
        action = payload.get("action")
        if action and action != expected_action:
            return False

    return True


def passes_request(expected_action: str) -> bool:
    """Check the Turnstile token of the current form request.

    The single call the views make. An empty token is passed on to
    `verify_token` as well, so that a Cloudflare outage (the widget cannot
    load) lets users through instead of locking them out.
    """
    token = (flask_request.form.get("cf-turnstile-response") or "").strip()
    return verify_token(
        token,
        remoteip=best_remote_ip(),
        timeout=3.0,
        expected_action=expected_action,
    )
