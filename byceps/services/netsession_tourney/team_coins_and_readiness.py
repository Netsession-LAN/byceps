"""
byceps.services.netsession_tourney.team_coins_and_readiness
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

What happens to coins and to a team's ready state when people leave.

Refunds go to whoever actually paid for the tournament (e.g. the former
captain after a captain change), and only as much as is still unrefunded.
"""

from sqlalchemy import func, select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyCoinLedgerEntry,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
)
from .models import CoinLedgerEntryKind, ParticipantStatus


_REGISTRATION_KINDS = (
    CoinLedgerEntryKind.tournament_registration_charge.value,
    CoinLedgerEntryKind.tournament_registration_refund.value,
)


def get_unrefunded_registration_coins(
    party_id: PartyID, user_id: UserID, tournament_id
) -> int:
    """Return the coins the user paid for the tournament and has not got
    back yet."""
    balance = db.session.scalar(
        select(
            func.coalesce(
                func.sum(DbNetsessionTourneyCoinLedgerEntry.amount_delta), 0
            )
        )
        .filter_by(
            party_id=party_id,
            user_id=user_id,
            reference_type='tournament',
            reference_id=str(tournament_id),
        )
        .filter(
            DbNetsessionTourneyCoinLedgerEntry.kind.in_(_REGISTRATION_KINDS)
        )
    )
    return max(0, -int(balance or 0))


def reset_ready_if_incomplete(
    db_participant: DbNetsessionTourneyParticipant, team_size: int | None
) -> None:
    """A team that lost a member is no longer ready."""
    if (
        team_size is None
        or db_participant.status != ParticipantStatus.ready.value
    ):
        return

    member_count = db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyTeamMember)
        .filter_by(participant_id=db_participant.id)
    )
    if member_count != team_size:  # same rule as when setting ready
        db_participant.status = ParticipantStatus.forming.value
