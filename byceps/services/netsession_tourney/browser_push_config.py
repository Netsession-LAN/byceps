"""
byceps.services.netsession_tourney.browser_push_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Party configuration of browser push notifications.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .browser_push_keys import (
    _ensure_browser_push_vapid_keys,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushConfig,
)
from .models import (
    BrowserPushConfig,
)
from .service_helpers import (
    db_browser_push_config_to_model,
)


def get_browser_push_config(party_id: PartyID) -> BrowserPushConfig:
    try:
        db_config = db.session.get(
            DbNetsessionTourneyBrowserPushConfig, party_id
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return _build_default_browser_push_config(party_id)
        raise

    if db_config is None:
        return _build_default_browser_push_config(party_id)

    return db_browser_push_config_to_model(db_config)


def is_browser_push_enabled_for_party(party_id: PartyID) -> bool:
    try:
        db_config = db.session.get(
            DbNetsessionTourneyBrowserPushConfig, party_id
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return False
        raise

    return bool(db_config and db_config.enabled and db_config.vapid_public_key)


def get_browser_push_public_key_for_party(party_id: PartyID) -> str | None:
    try:
        db_config = db.session.get(
            DbNetsessionTourneyBrowserPushConfig, party_id
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return None
        raise

    if db_config is None or not db_config.enabled:
        return None

    return db_config.vapid_public_key


def configure_browser_push(
    party_id: PartyID,
    *,
    enabled: bool,
) -> Result[BrowserPushConfig, str]:
    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unbekannte Party.')

    try:
        db_config = db.session.get(
            DbNetsessionTourneyBrowserPushConfig, party_id
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return Err(
                'Die Tabellen für Browser-Benachrichtigungen fehlen noch.'
            )
        raise

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyBrowserPushConfig(party_id, now)
        db.session.add(db_config)

    if enabled:
        _ensure_browser_push_vapid_keys(db_config)

    db_config.enabled = enabled
    db_config.updated_at = now
    db.session.commit()

    return Ok(db_browser_push_config_to_model(db_config))


def _build_default_browser_push_config(
    party_id: PartyID,
) -> BrowserPushConfig:
    now = datetime.utcnow()
    return BrowserPushConfig(
        party_id=party_id,
        enabled=False,
        vapid_public_key=None,
        created_at=now,
        updated_at=now,
    )


def is_missing_browser_push_table_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if sqlstate != '42P01':
        return False

    statement = str(getattr(exc, 'statement', '') or '')
    return 'netsession_tourney_browser_push_' in statement
