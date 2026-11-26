"""
byceps.services.netsession_tourney.coin_service_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Coin settings: the party's coin configuration and the per ticket
category coin amounts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyCoinSettings,
    DbNetsessionTourneyTicketCategoryCoinSettings,
)
from .models import (
    CoinSettings,
    TicketCategoryCoinSettings,
)
from .service_helpers import (
    db_coin_settings_to_model,
    db_ticket_category_coin_settings_to_model,
)


def get_coin_settings(party_id: PartyID) -> CoinSettings:
    db_settings = db.session.get(DbNetsessionTourneyCoinSettings, party_id)
    if db_settings is None:
        return _build_default_coin_settings(party_id)

    return db_coin_settings_to_model(db_settings)


def get_ticket_category_coin_settings_for_party(
    party_id: PartyID,
) -> list[TicketCategoryCoinSettings]:
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyTicketCategoryCoinSettings)
        .filter_by(party_id=party_id)
        .order_by(
            DbNetsessionTourneyTicketCategoryCoinSettings.ticket_category_id.asc()
        )
    ).all()

    return [
        db_ticket_category_coin_settings_to_model(db_row) for db_row in db_rows
    ]


def configure_coin_settings(
    party_id: PartyID,
    initiator: User,
    *,
    enabled: bool,
    default_coin_amount: int,
    ticket_category_coin_amounts: dict[Any, int],
) -> Result[CoinSettings, str]:
    _ = initiator

    error = _validate_coin_amounts(
        default_coin_amount, ticket_category_coin_amounts
    )
    if error is not None:
        return Err(error)

    now = datetime.utcnow()
    _upsert_coin_settings_row(party_id, now, enabled, default_coin_amount)
    _sync_ticket_category_coin_rows(party_id, ticket_category_coin_amounts, now)

    db.session.commit()
    return Ok(get_coin_settings(party_id))


def _validate_coin_amounts(
    default_coin_amount: int, ticket_category_coin_amounts: dict[Any, int]
) -> str | None:
    if default_coin_amount < 0:
        return 'Die Standard-Coins dürfen nicht negativ sein.'

    for amount in ticket_category_coin_amounts.values():
        if amount < 0:
            return 'Die Coins pro Ticketkategorie dürfen nicht negativ sein.'

    return None


def _upsert_coin_settings_row(
    party_id: PartyID, now: datetime, enabled: bool, default_coin_amount: int
) -> None:
    db_settings = db.session.get(DbNetsessionTourneyCoinSettings, party_id)
    if db_settings is None:
        db_settings = DbNetsessionTourneyCoinSettings(
            party_id,
            now,
            enabled=enabled,
            default_coin_amount=default_coin_amount,
        )
        db.session.add(db_settings)
    else:
        db_settings.enabled = enabled
        db_settings.default_coin_amount = default_coin_amount
        db_settings.updated_at = now


def _sync_ticket_category_coin_rows(
    party_id: PartyID,
    ticket_category_coin_amounts: dict[Any, int],
    now: datetime,
) -> None:
    existing_rows = {
        db_row.ticket_category_id: db_row
        for db_row in db.session.scalars(
            select(DbNetsessionTourneyTicketCategoryCoinSettings).filter_by(
                party_id=party_id
            )
        ).all()
    }

    normalized_ids = set(ticket_category_coin_amounts.keys())

    for ticket_category_id, amount in ticket_category_coin_amounts.items():
        db_row = existing_rows.get(ticket_category_id)
        if db_row is None:
            db.session.add(
                DbNetsessionTourneyTicketCategoryCoinSettings(
                    party_id,
                    ticket_category_id,
                    amount,
                    now,
                )
            )
            continue

        db_row.coin_amount = amount
        db_row.updated_at = now

    for ticket_category_id, db_row in existing_rows.items():
        if ticket_category_id not in normalized_ids:
            db.session.delete(db_row)


def validate_coin_cost(coin_cost: int) -> Result[None, str]:
    if coin_cost < 0:
        return Err('Die Coin-Kosten dürfen nicht negativ sein.')

    return Ok(None)


def _build_default_coin_settings(party_id: PartyID) -> CoinSettings:
    now = datetime.utcnow()
    return CoinSettings(
        party_id=party_id,
        enabled=False,
        default_coin_amount=0,
        created_at=now,
        updated_at=now,
    )
