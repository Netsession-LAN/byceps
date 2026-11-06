"""
byceps.services.netsession_tourney.coin_cancel_refunds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a tournament is canceled, everybody gets back the coins they paid for
it – regardless of the tournament's refund policy, because the organizers
called it off.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID

from .coin_service import append_coin_ledger_entry
from .dbmodels import DbNetsessionTourneyCoinLedgerEntry
from .models import CoinLedgerEntryKind, Tournament
from .team_coins_and_readiness import get_unrefunded_registration_coins


def refund_all_coins_of_canceled_tournament(
    party_id: PartyID, tournament: Tournament, initiator_id: UserID
) -> int:
    """Refund what is still unrefunded; return the number of refunds.

    Runs within the caller's transaction.
    """
    payer_ids = db.session.scalars(
        select(DbNetsessionTourneyCoinLedgerEntry.user_id)
        .filter_by(
            party_id=party_id,
            reference_type='tournament',
            reference_id=str(tournament.id),
            kind=CoinLedgerEntryKind.tournament_registration_charge.value,
        )
        .distinct()
    ).all()

    now = datetime.utcnow()
    refund_count = 0
    for user_id in payer_ids:
        unrefunded = get_unrefunded_registration_coins(
            party_id, user_id, tournament.id
        )
        if not unrefunded:
            continue
        append_coin_ledger_entry(
            party_id,
            user_id,
            unrefunded,
            CoinLedgerEntryKind.tournament_registration_refund,
            now,
            reference_type='tournament',
            reference_id=str(tournament.id),
            note=tournament.title,
            created_by_user_id=initiator_id,
        )
        refund_count += 1
    return refund_count
