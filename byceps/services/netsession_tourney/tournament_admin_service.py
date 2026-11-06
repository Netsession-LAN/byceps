"""
byceps.services.netsession_tourney.tournament_admin_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Users that may administrate a single tournament.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyTournamentAdmin,
)
from .models import (
    TournamentAdminID,
    TournamentID,
)
from .service_helpers import (
    append_audit_log,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


def get_tournament_admin_user_ids(tournament_id: TournamentID) -> set[UserID]:
    user_ids = db.session.scalars(
        select(DbNetsessionTourneyTournamentAdmin.user_id).filter_by(
            tournament_id=tournament_id
        )
    ).all()

    return set(user_ids)


def set_tournament_admin_user_ids(
    party_id: PartyID,
    tournament_id: TournamentID,
    admin_user_ids: set[UserID],
    initiator: User,
) -> Result[set[UserID], str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_user_ids = set(admin_user_ids)

    db.session.execute(
        delete(DbNetsessionTourneyTournamentAdmin).where(
            DbNetsessionTourneyTournamentAdmin.tournament_id == tournament_id
        )
    )

    now = datetime.utcnow()
    for user_id in sorted(normalized_user_ids, key=str):
        db.session.add(
            DbNetsessionTourneyTournamentAdmin(
                TournamentAdminID(generate_uuid7()),
                tournament_id,
                user_id,
                now,
            )
        )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_admins_set',
        payload={'admin_user_ids': [str(user_id) for user_id in sorted(normalized_user_ids, key=str)]},
        created_at=now,
    )

    db.session.commit()
    return Ok(normalized_user_ids)
