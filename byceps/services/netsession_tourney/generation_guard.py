"""
byceps.services.netsession_tourney.generation_guard
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generating the matches of a phase replaces its existing matches – with
their results, chats and report receipts. That is refused once a result
was reported in the phase, for closed or canceled tournaments, and
before the check-in window has ended.
"""

from __future__ import annotations

from byceps.database import db

from . import checkin_service
from .dbmodels import DbNetsessionTourneyTournament
from .models import Stage, StageID, Tournament, TournamentStatus
from .service_helpers import db_tournament_to_model
from .stage_service import stage_has_reported_results


def check_generation_allowed(tournament: Tournament, stage_id: StageID) -> str | None:
    """Return why the matches of the phase must not be (re)generated, or
    None."""
    if tournament.status in {TournamentStatus.closed, TournamentStatus.canceled}:
        return (
            'Abgeschlossene oder abgesagte Turniere lassen sich nicht neu '
            'erzeugen.'
        )
    if stage_has_reported_results(tournament.id, stage_id):
        return (
            'In dieser Phase gibt es schon gemeldete Ergebnisse. Neu erzeugen '
            'würde sie löschen; lösche bei Bedarf zuerst die Ergebnisse.'
        )
    return checkin_service.check_generation_allowed(tournament)


def check_generation_allowed_for_stage(stage: Stage) -> str | None:
    """Like `check_generation_allowed`, loading the stage's tournament."""
    db_tournament = db.session.get(DbNetsessionTourneyTournament, stage.tournament_id)
    if db_tournament is None:
        return None
    return check_generation_allowed(db_tournament_to_model(db_tournament), stage.id)
