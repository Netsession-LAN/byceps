"""
byceps.services.netsession_tourney.registration_locks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Registrations that happen at the same time run one after the other: the
tournament row is locked (participant limit, one team per captain) and so
is the user's coin account (coins must not drop below zero across
tournaments). Both locks are held until the transaction ends.
"""

from __future__ import annotations

from sqlalchemy import select, text

from byceps.database import db
from byceps.services.user.models import UserID

from .dbmodels import DbNetsessionTourneyTournament
from .models import TournamentID


def lock_tournament_for_registration(tournament_id: TournamentID) -> None:
    db.session.execute(
        select(DbNetsessionTourneyTournament.id)
        .filter_by(id=tournament_id)
        .with_for_update()
    )


def lock_user_coins(user_id: UserID) -> None:
    db.session.execute(
        text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
        {'key': f'netsession-tourney-coins:{user_id}'},
    )
