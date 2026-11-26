"""
byceps.services.netsession_tourney.match_schedule_generated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Scheduling freshly generated matches round by round.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
)
from .models import (
    MatchID,
    Stage,
)
from .stage_service import (
    get_stage_setting_int,
)


def schedule_generated_matches(
    *,
    tournament_starts_at: datetime | None,
    stage: Stage,
    match_ids: list[MatchID],
    round_starts_at_by_round_no: dict[int, datetime] | None = None,
) -> None:
    if not match_ids:
        return

    round_starts_at_overrides = _get_round_starts_at_overrides(
        round_starts_at_by_round_no
    )

    match_duration_minutes = get_stage_setting_int(
        stage.settings, 'match_duration_minutes', minimum=1
    )
    max_matches_per_round = get_stage_setting_int(
        stage.settings, 'max_matches_per_round', minimum=1
    )
    break_between_rounds_minutes = get_stage_setting_int(
        stage.settings,
        'break_between_rounds_minutes',
        minimum=0,
        fallback=0,
    )

    db_matches_by_round_no = _get_db_matches_by_round_no(match_ids)
    if not db_matches_by_round_no:
        return

    if not _has_generated_match_schedule_basis(
        tournament_starts_at, round_starts_at_overrides, match_duration_minutes
    ):
        return

    _schedule_generated_rounds(
        db_matches_by_round_no,
        tournament_starts_at,
        round_starts_at_overrides,
        match_duration_minutes=match_duration_minutes,
        max_matches_per_round=max_matches_per_round,
        break_between_rounds_minutes=break_between_rounds_minutes,
    )


def _get_round_starts_at_overrides(
    round_starts_at_by_round_no: dict[int, datetime] | None,
) -> dict[int, datetime]:
    return {
        round_no: starts_at
        for round_no, starts_at in (round_starts_at_by_round_no or {}).items()
        if round_no > 0
    }


def _has_generated_match_schedule_basis(
    tournament_starts_at: datetime | None,
    round_starts_at_overrides: dict[int, datetime],
    match_duration_minutes: int | None,
) -> bool:
    """Scheduling needs round start overrides, or both a tournament start
    and a match duration."""
    if round_starts_at_overrides:
        return True

    return (
        match_duration_minutes is not None and tournament_starts_at is not None
    )


def _schedule_generated_rounds(
    db_matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]],
    tournament_starts_at: datetime | None,
    round_starts_at_overrides: dict[int, datetime],
    *,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
) -> None:
    round_starts_at = tournament_starts_at
    for round_no in sorted(db_matches_by_round_no.keys()):
        db_round_matches = db_matches_by_round_no[round_no]
        round_override_starts_at = round_starts_at_overrides.get(round_no)
        if round_override_starts_at is not None:
            round_starts_at = round_override_starts_at
        if round_starts_at is None:
            continue

        if match_duration_minutes is None:
            _schedule_round_matches_at_override(
                db_round_matches, round_override_starts_at, round_starts_at
            )
            continue

        wave_count = _schedule_round_matches_in_waves(
            db_round_matches,
            round_starts_at,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
        )

        round_starts_at += timedelta(
            minutes=(wave_count * match_duration_minutes)
            + break_between_rounds_minutes
        )


def _schedule_round_matches_at_override(
    db_round_matches: list[DbNetsessionTourneyMatch],
    round_override_starts_at: datetime | None,
    round_starts_at: datetime,
) -> None:
    """Without a match duration, only rounds with an explicit start time
    are scheduled."""
    if round_override_starts_at is None:
        return

    for db_match in db_round_matches:
        db_match.scheduled_at = round_starts_at


def _get_db_matches_by_round_no(
    match_ids: list[MatchID],
) -> dict[int, list[DbNetsessionTourneyMatch]]:
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter(DbNetsessionTourneyMatch.id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()

    db_matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = (
        defaultdict(list)
    )
    for db_match in db_matches:
        db_matches_by_round_no[db_match.round_no].append(db_match)

    return db_matches_by_round_no


def _schedule_round_matches_in_waves(
    db_round_matches: list[DbNetsessionTourneyMatch],
    round_starts_at: datetime,
    *,
    match_duration_minutes: int,
    max_matches_per_round: int | None,
) -> int:
    """Schedule the round's matches in waves of at most
    `max_matches_per_round` concurrent matches; return the number of waves."""
    max_concurrent_matches = max_matches_per_round or len(db_round_matches)

    wave_count = 0
    for index, db_match in enumerate(db_round_matches):
        wave_no = index // max_concurrent_matches
        db_match.scheduled_at = round_starts_at + timedelta(
            minutes=wave_no * match_duration_minutes
        )
        wave_count = max(wave_count, wave_no + 1)

    return wave_count
