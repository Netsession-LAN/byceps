"""
byceps.services.netsession_tourney.match_schedule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Times of matches: schedule of generated rounds, rescheduling, storing generated matches.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
)
from .engines.base import MatchSpec, SlotSpec
from .engines.registry import (
    find_stage_engine,
)
from .models import (
    Match,
    MatchID,
    MatchSlotID,
    MatchState,
    ParticipantID,
    Stage,
    StageID,
    StageStatus,
    StageType,
    TournamentID,
)
from .notification_service import (
    _append_notifications_for_match,
)
from .service_helpers import (
    _append_audit_log,
    _db_match_to_model,
    _parse_source_outcome,
)
from .stage_service import (
    _get_stage_setting_int,
)
from .tournament_queries import (
    _build_site_match_path,
    _find_db_tournament_for_party,
)


log = structlog.get_logger()


def _build_pending_structure_match_specs_for_stage(
    *,
    tournament_id: TournamentID,
    stage_type: StageType,
    participant_count: int,
) -> Result[list[MatchSpec], str]:
    engine = find_stage_engine(stage_type)
    if engine is None:
        return Err('Für diesen Stage-Typ gibt es noch keine Match-Erzeugung.')

    preview_stage = Stage(
        id=StageID(generate_uuid7()),
        tournament_id=tournament_id,
        order_no=1,
        type=stage_type,
        name='Preview',
        settings={},
        status=StageStatus.draft,
    )
    preview_participant_ids = [
        ParticipantID(generate_uuid7()) for _ in range(participant_count)
    ]
    generated_specs_result = engine.generate(
        preview_stage, preview_participant_ids
    )
    if generated_specs_result.is_err():
        return Err(generated_specs_result.unwrap_err())

    pending_specs = [
        MatchSpec(
            round_no=spec.round_no,
            match_no=spec.match_no,
            state='pending',
            slots=[
                SlotSpec(
                    slot_no=slot.slot_no,
                    participant_id=None,
                    source_match_no=slot.source_match_no,
                    source_outcome=slot.source_outcome,
                )
                for slot in spec.slots
            ],
        )
        for spec in generated_specs_result.unwrap()
    ]

    return Ok(pending_specs)


def reschedule_match(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    scheduled_at: datetime,
    initiator: User,
    *,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Match, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    comment = comment.strip()
    if not comment:
        return Err('Bitte einen Kommentar angeben.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    db_match.scheduled_at = scheduled_at
    db_match.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_rescheduled',
        payload={
            'scheduled_at': scheduled_at.isoformat(),
            'comment': comment,
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )

    _append_notifications_for_match(
        db_match,
        actor_user_id=initiator.id,
        kind='schedule_changed',
        payload={
            'match_id': str(db_match.id),
            'scheduled_at': scheduled_at.isoformat(),
            'url': _build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    db.session.commit()

    log.info(
        'netsession_tourney.match_rescheduled',
        tournament_id=str(tournament_id),
        match_id=str(match_id),
        actor_user_id=str(initiator.id),
        correlation_id=correlation_id,
    )

    return Ok(_db_match_to_model(db_match))


def _persist_generated_matches(
    *,
    tournament_id: TournamentID,
    stage_id: StageID,
    specs: list[MatchSpec],
    match_settings_by_round_and_match_no: (
        dict[tuple[int, int], dict[str, Any]] | None
    ) = None,
) -> list[Match]:
    now = datetime.utcnow()
    match_id_by_match_no: dict[int, MatchID] = {}
    source_slot_id_by_match_no: dict[int, MatchSlotID] = {}
    created_matches: list[DbNetsessionTourneyMatch] = []

    for spec in specs:
        db_match = DbNetsessionTourneyMatch(
            MatchID(generate_uuid7()),
            tournament_id,
            stage_id,
            spec.round_no,
            spec.match_no,
            now,
            state=MatchState(spec.state),
            settings_json=dict(
                (match_settings_by_round_and_match_no or {}).get(
                    (spec.round_no, spec.match_no), {}
                )
            ),
        )
        db.session.add(db_match)
        created_matches.append(db_match)
        match_id_by_match_no[spec.match_no] = db_match.id

    db.session.flush()

    for spec in specs:
        for slot in spec.slots:
            source_slot_id = None
            if slot.source_match_no is not None:
                source_slot_id = source_slot_id_by_match_no.get(slot.source_match_no)
            db_slot = DbNetsessionTourneyMatchSlot(
                MatchSlotID(generate_uuid7()),
                match_id_by_match_no[spec.match_no],
                slot.slot_no,
                participant_id=slot.participant_id,
                source_match_slot_id=source_slot_id,
                source_outcome=_parse_source_outcome(slot.source_outcome),
            )
            db.session.add(db_slot)
            if slot.slot_no == 1:
                source_slot_id_by_match_no[spec.match_no] = db_slot.id

    db.session.flush()
    return [_db_match_to_model(item) for item in created_matches]


def _schedule_generated_matches(
    *,
    tournament_starts_at: datetime | None,
    stage: Stage,
    match_ids: list[MatchID],
    round_starts_at_by_round_no: dict[int, datetime] | None = None,
) -> None:
    if not match_ids:
        return

    round_starts_at_overrides = {
        round_no: starts_at
        for round_no, starts_at in (round_starts_at_by_round_no or {}).items()
        if round_no > 0
    }

    match_duration_minutes = _get_stage_setting_int(
        stage.settings, 'match_duration_minutes', minimum=1
    )
    max_matches_per_round = _get_stage_setting_int(
        stage.settings, 'max_matches_per_round', minimum=1
    )
    break_between_rounds_minutes = _get_stage_setting_int(
        stage.settings,
        'break_between_rounds_minutes',
        minimum=0,
        fallback=0,
    )

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter(DbNetsessionTourneyMatch.id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return

    db_matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = defaultdict(
        list
    )
    for db_match in db_matches:
        db_matches_by_round_no[db_match.round_no].append(db_match)

    if (
        tournament_starts_at is None
        and not round_starts_at_overrides
        and match_duration_minutes is None
    ):
        return
    if match_duration_minutes is None and not round_starts_at_overrides:
        return
    if tournament_starts_at is None and not round_starts_at_overrides:
        return

    round_starts_at = tournament_starts_at
    for round_no in sorted(db_matches_by_round_no.keys()):
        db_round_matches = db_matches_by_round_no[round_no]
        round_override_starts_at = round_starts_at_overrides.get(round_no)
        if round_override_starts_at is not None:
            round_starts_at = round_override_starts_at
        if round_starts_at is None:
            continue

        if match_duration_minutes is None:
            if round_override_starts_at is None:
                continue
            for db_match in db_round_matches:
                db_match.scheduled_at = round_starts_at
            continue

        max_concurrent_matches = max_matches_per_round or len(db_round_matches)

        wave_count = 0
        for index, db_match in enumerate(db_round_matches):
            wave_no = index // max_concurrent_matches
            db_match.scheduled_at = round_starts_at + timedelta(
                minutes=wave_no * match_duration_minutes
            )
            wave_count = max(wave_count, wave_no + 1)

        round_starts_at += timedelta(
            minutes=(wave_count * match_duration_minutes)
            + break_between_rounds_minutes
        )


def _build_round_starts_at_schedule(
    *,
    tournament_starts_at: datetime | None,
    stage: Stage,
    round_match_counts: dict[int, int],
) -> dict[int, datetime]:
    if tournament_starts_at is None or not round_match_counts:
        return {}

    match_duration_minutes = _get_stage_setting_int(
        stage.settings, 'match_duration_minutes', minimum=1
    )
    if match_duration_minutes is None:
        return {}

    max_matches_per_round = _get_stage_setting_int(
        stage.settings, 'max_matches_per_round', minimum=1
    )
    break_between_rounds_minutes = _get_stage_setting_int(
        stage.settings,
        'break_between_rounds_minutes',
        minimum=0,
        fallback=0,
    )

    schedule: dict[int, datetime] = {}
    round_starts_at = tournament_starts_at
    for round_no in sorted(round_match_counts.keys()):
        match_count = round_match_counts[round_no]
        if match_count < 1:
            continue

        schedule[round_no] = round_starts_at
        max_concurrent_matches = max_matches_per_round or match_count
        wave_count = (
            (match_count + max_concurrent_matches - 1)
            // max_concurrent_matches
        )
        round_starts_at += timedelta(
            minutes=(wave_count * match_duration_minutes)
            + break_between_rounds_minutes
        )

    return schedule
