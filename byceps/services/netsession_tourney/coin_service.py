"""
byceps.services.netsession_tourney.coin_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Coins: settings, balances, manual adjustments, charges and refunds for tournament registrations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_service
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyCoinLedgerEntry,
    DbNetsessionTourneyCoinSettings,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTicketCategoryCoinSettings,
)
from .models import (
    CoinLedgerEntry,
    CoinLedgerEntryID,
    CoinLedgerEntryKind,
    CoinRefundPolicy,
    CoinSettings,
    MatchState,
    TicketCategoryCoinSettings,
    Tournament,
    TournamentStatus,
    UserCoinBalance,
)
from .registration_locks import lock_user_coins
from .service_helpers import (
    append_audit_log,
    db_coin_ledger_entry_to_model,
    db_coin_settings_to_model,
    db_ticket_category_coin_settings_to_model,
)
from .team_coins_and_readiness import (
    get_unrefunded_registration_coins,
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

    if default_coin_amount < 0:
        return Err('Die Standard-Coins dürfen nicht negativ sein.')

    for amount in ticket_category_coin_amounts.values():
        if amount < 0:
            return Err('Die Coins pro Ticketkategorie dürfen nicht negativ sein.')

    now = datetime.utcnow()
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

    db.session.commit()
    return Ok(get_coin_settings(party_id))


def get_user_coin_balance(party_id: PartyID, user_id: UserID) -> UserCoinBalance:
    ticket_coin_amount = _get_ticket_coin_amount_for_user(party_id, user_id)
    manual_adjustment_amount = _get_manual_coin_adjustment_amount_for_user(
        party_id, user_id
    )
    registration_delta_amount = _get_registration_coin_delta_amount_for_user(
        party_id, user_id
    )

    return UserCoinBalance(
        party_id=party_id,
        user_id=user_id,
        ticket_coin_amount=ticket_coin_amount,
        manual_adjustment_amount=manual_adjustment_amount,
        registration_delta_amount=registration_delta_amount,
        available_coins=(
            ticket_coin_amount
            + manual_adjustment_amount
            + registration_delta_amount
        ),
    )


def get_user_coin_balances(
    party_id: PartyID, user_ids: set[UserID]
) -> dict[UserID, UserCoinBalance]:
    return {
        user_id: get_user_coin_balance(party_id, user_id)
        for user_id in user_ids
    }


def get_recent_coin_ledger_entries_for_user(
    party_id: PartyID, user_id: UserID, *, limit: int = 10
) -> list[CoinLedgerEntry]:
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyCoinLedgerEntry)
        .filter_by(party_id=party_id, user_id=user_id)
        .order_by(DbNetsessionTourneyCoinLedgerEntry.created_at.desc())
        .limit(limit)
    ).all()

    return [db_coin_ledger_entry_to_model(db_row) for db_row in db_rows]


def adjust_user_coins(
    party_id: PartyID,
    user_id: UserID,
    amount_delta: int,
    note: str,
    initiator: User,
) -> Result[UserCoinBalance, str]:
    if amount_delta == 0:
        return Err('Der Betrag darf nicht 0 sein.')
    if get_user_coin_balance(party_id, user_id).available_coins + amount_delta < 0:
        return Err('Das Coin-Guthaben darf nicht negativ werden.')

    note_clean = note.strip() or None
    now = datetime.utcnow()
    db.session.add(
        DbNetsessionTourneyCoinLedgerEntry(
            CoinLedgerEntryID(generate_uuid7()),
            party_id,
            user_id,
            amount_delta,
            CoinLedgerEntryKind.admin_adjustment.value,
            now,
            note=note_clean,
            created_by_user_id=initiator.id,
        )
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='user',
        object_id=user_id,
        action='coin_balance_adjusted',
        payload={
            'party_id': party_id,
            'user_id': str(user_id),
            'amount_delta': amount_delta,
            'note': note_clean,
        },
        created_at=now,
    )

    db.session.commit()
    return Ok(get_user_coin_balance(party_id, user_id))


def is_tournament_coin_refund_available(tournament: Tournament) -> bool:
    if tournament.status in {
        TournamentStatus.closed,
        TournamentStatus.canceled,
    }:
        return False

    if (
        tournament.coin_refund_policy
        == CoinRefundPolicy.until_tournament_end
    ):
        return True

    first_stage_id = db.session.scalar(
        select(DbNetsessionTourneyStage.id)
        .filter_by(tournament_id=tournament.id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
        .limit(1)
    )
    if first_stage_id is None:
        return True

    round_one_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament.id,
            stage_id=first_stage_id,
            round_no=1,
        )
    )
    if not round_one_match_count:
        return True

    completed_round_one_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament.id,
            stage_id=first_stage_id,
            round_no=1,
            state=MatchState.completed.value,
        )
    )

    return int(completed_round_one_match_count or 0) < int(
        round_one_match_count or 0
    )


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


def _get_ticket_coin_amount_for_user(party_id: PartyID, user_id: UserID) -> int:
    coin_settings = get_coin_settings(party_id)
    tickets = ticket_service.get_tickets_used_by_user(user_id, party_id)
    if not tickets:
        return 0

    amount_by_category_id = {
        item.ticket_category_id: item.coin_amount
        for item in get_ticket_category_coin_settings_for_party(party_id)
    }

    return max(
        amount_by_category_id.get(ticket.category_id, coin_settings.default_coin_amount)
        for ticket in tickets
    )


def _get_manual_coin_adjustment_amount_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    amount = db.session.scalar(
        select(db.func.coalesce(db.func.sum(DbNetsessionTourneyCoinLedgerEntry.amount_delta), 0))
        .filter_by(
            party_id=party_id,
            user_id=user_id,
            kind=CoinLedgerEntryKind.admin_adjustment.value,
        )
    )
    return int(amount or 0)


def _get_registration_coin_delta_amount_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    amount = db.session.scalar(
        select(db.func.coalesce(db.func.sum(DbNetsessionTourneyCoinLedgerEntry.amount_delta), 0))
        .filter_by(party_id=party_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyCoinLedgerEntry.kind.in_(
                [
                    CoinLedgerEntryKind.tournament_registration_charge.value,
                    CoinLedgerEntryKind.tournament_registration_refund.value,
                ]
            )
        )
    )
    return int(amount or 0)


def append_coin_ledger_entry(
    party_id: PartyID,
    user_id: UserID,
    amount_delta: int,
    kind: CoinLedgerEntryKind,
    created_at: datetime,
    *,
    reference_type: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    created_by_user_id: UserID | None = None,
) -> None:
    db.session.add(
        DbNetsessionTourneyCoinLedgerEntry(
            CoinLedgerEntryID(generate_uuid7()),
            party_id,
            user_id,
            amount_delta,
            kind.value,
            created_at,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_by_user_id=created_by_user_id,
        )
    )


def charge_coins_for_tournament_registration(
    party_id: PartyID,
    tournament: Tournament,
    user_id: UserID,
    *,
    created_by_user_id: UserID | None = None,
) -> Result[None, str]:
    coin_settings = get_coin_settings(party_id)
    if not coin_settings.enabled or tournament.coin_cost <= 0:
        return Ok(None)

    lock_user_coins(user_id)  # simultaneous charges must not overdraw
    balance = get_user_coin_balance(party_id, user_id)
    if balance.available_coins < tournament.coin_cost:
        return Err(
            f'Nicht genügend Coins. Benötigt: {tournament.coin_cost}, verfügbar: {balance.available_coins}.'
        )

    append_coin_ledger_entry(
        party_id,
        user_id,
        -tournament.coin_cost,
        CoinLedgerEntryKind.tournament_registration_charge,
        datetime.utcnow(),
        reference_type='tournament',
        reference_id=str(tournament.id),
        note=tournament.title,
        created_by_user_id=created_by_user_id,
    )
    return Ok(None)


def refund_coins_for_tournament_registration_if_available(
    party_id: PartyID,
    tournament: Tournament,
    user_id: UserID,
    *,
    created_by_user_id: UserID | None = None,
) -> None:
    coin_settings = get_coin_settings(party_id)
    if not coin_settings.enabled or tournament.coin_cost <= 0:
        return

    paid = get_unrefunded_registration_coins(party_id, user_id, tournament.id)
    if not paid or not is_tournament_coin_refund_available(tournament):
        return

    append_coin_ledger_entry(
        party_id,
        user_id,
        paid,
        CoinLedgerEntryKind.tournament_registration_refund,
        datetime.utcnow(),
        reference_type='tournament',
        reference_id=str(tournament.id),
        note=tournament.title,
        created_by_user_id=created_by_user_id,
    )
