"""
byceps.services.netsession_tourney.tournament_closing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks before a tournament is closed (finished).
"""

from sqlalchemy import func, select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .dbmodels import DbNetsessionTourneyMatch, DbNetsessionTourneyTournament
from .models import MatchState, TournamentStatus


# Matches that still wait for players, a confirmation or an admin.
OPEN_MATCH_STATES = frozenset(
    state.value
    for state in (
        MatchState.ready,
        MatchState.in_progress,
        MatchState.pending_confirmation,
        MatchState.needs_admin_review,
        MatchState.disputed,
    )
)


def validate_can_close(
    db_tournament: DbNetsessionTourneyTournament,
) -> Result[None, str]:
    if db_tournament.status == TournamentStatus.closed.value:
        return Err('Das Turnier ist bereits abgeschlossen.')

    if db_tournament.status == TournamentStatus.canceled.value:
        return Err('Abgesagte Turniere können nicht abgeschlossen werden.')

    open_count = count_open_matches(db_tournament.id)
    if open_count:
        return Err(
            f'Es sind noch {open_count} Matches offen. Bitte erst alle '
            'Ergebnisse eintragen (oder die Matches als Walkover werten).'
        )

    return Ok(None)


def count_open_matches(tournament_id) -> int:
    return db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyMatch)
        .filter(DbNetsessionTourneyMatch.tournament_id == tournament_id)
        .filter(DbNetsessionTourneyMatch.state.in_(OPEN_MATCH_STATES))
    )
