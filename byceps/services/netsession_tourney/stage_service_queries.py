"""
byceps.services.netsession_tourney.stage_service_queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Read-only stage queries: completion, assigned participants, reported
results and integer settings.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchState,
    StageID,
    TournamentID,
)


def is_stage_fully_completed(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    total_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
    )
    if not total_match_count:
        return False

    incomplete_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id))
        .filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
        .filter(DbNetsessionTourneyMatch.state != MatchState.completed.value)
    )
    return int(incomplete_match_count or 0) == 0


def stage_has_assigned_participants(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    assigned_participant_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchSlot.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id
            == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
            DbNetsessionTourneyMatchSlot.participant_id.is_not(None),
        )
    )
    return bool(assigned_participant_count)


def stage_has_reported_results(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    result_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchResult.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id
            == DbNetsessionTourneyMatchResult.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
        )
    )
    return bool(result_count)


def get_stage_setting_int(
    settings: dict[str, Any],
    key: str,
    *,
    minimum: int,
    fallback: int | None = None,
) -> int | None:
    raw_value = settings.get(key, fallback)
    if raw_value is None:
        return None

    try:
        value = int(raw_value)
    except TypeError, ValueError:
        return fallback

    if value < minimum:
        return fallback

    return value
