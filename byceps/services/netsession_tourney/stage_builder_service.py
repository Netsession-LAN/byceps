"""
byceps.services.netsession_tourney.stage_builder_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: creating the stages of a planned tournament format.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .ffa_stage_builder_plan import (
    _build_ffa_stage_builder_plan,
)
from .match_schedule import (
    _build_pending_structure_match_specs_for_stage,
    _persist_generated_matches,
)
from .models import (
    Stage,
    StageID,
    StageType,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .stage_builder_parts import (
    StageTiming,
    audit_created_stages,
    duel_main_stage_settings,
    duel_preliminary_settings,
    validate_duel_builder_input,
)
from .service_helpers import (
    _db_stage_to_model,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


def build_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
    initiator: User,
) -> Result[list[Stage], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err(
            'Die Stage-Struktur kann nur im Draft-Status aufgebaut werden.'
        )

    existing_stage_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyStage.id)).filter_by(
            tournament_id=tournament_id
        )
    )
    if existing_stage_count:
        return Err(
            'Für den Stage Builder V1 muss das Turnier noch keine Stages haben.'
        )

    tournament_mode = TournamentMode(db_tournament.mode)
    if tournament_mode == TournamentMode.ffa:
        return _build_ffa_stage_builder_plan(
            party_id,
            tournament_id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
            initiator=initiator,
        )

    if tournament_mode != TournamentMode.duel:
        return Err('Der Stage Builder V1 unterstützt diesen Turniermodus nicht.')

    return _build_duel_stage_builder_plan(
        tournament_id,
        generation_basis=generation_basis,
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        preliminary_type=preliminary_type,
        round_robin_builder_mode=round_robin_builder_mode,
        round_robin_group_count=round_robin_group_count,
        swiss_threshold=swiss_threshold,
        timing=StageTiming(
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
        ),
        initiator=initiator,
    )


def _build_duel_stage_builder_plan(
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    timing: StageTiming,
    initiator: User,
) -> Result[list[Stage], str]:
    input_error = validate_duel_builder_input(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        generation_basis=generation_basis,
        preliminary_type=preliminary_type,
        round_robin_builder_mode=round_robin_builder_mode,
        round_robin_group_count=round_robin_group_count,
        swiss_threshold=swiss_threshold,
        timing=timing,
    )
    if input_error is not None:
        return Err(input_error)

    now = datetime.utcnow()
    created_stages: list[DbNetsessionTourneyStage] = []

    preliminary_stage: DbNetsessionTourneyStage | None = None
    if preliminary_type is not None:
        preliminary_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            1,
            preliminary_type,
            'Vorrunde',
            now,
            settings_json=duel_preliminary_settings(
                preliminary_type=preliminary_type,
                generation_basis=generation_basis,
                main_stage_size=main_stage_size,
                round_robin_builder_mode=round_robin_builder_mode,
                round_robin_group_count=round_robin_group_count,
                swiss_threshold=swiss_threshold,
                timing=timing,
            ),
        )
        db.session.add(preliminary_stage)
        created_stages.append(preliminary_stage)

    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        2 if preliminary_stage is not None else 1,
        main_stage_type,
        'Hauptturnier',
        now,
        settings_json=duel_main_stage_settings(
            generation_basis=generation_basis,
            main_stage_size=main_stage_size,
            preliminary_stage=preliminary_stage,
            preliminary_type=preliminary_type,
            timing=timing,
        ),
    )
    db.session.add(main_stage)
    created_stages.append(main_stage)

    if preliminary_stage is not None:
        structure_result = _add_main_stage_structure(
            tournament_id, main_stage, main_stage_type, main_stage_size
        )
        if structure_result.is_err():
            return structure_result

    audit_created_stages(created_stages, initiator, now)
    db.session.commit()

    return Ok([_db_stage_to_model(stage) for stage in created_stages])


def _add_main_stage_structure(
    tournament_id, main_stage, main_stage_type, main_stage_size
) -> Result[None, str]:
    """With a preliminary, the main stage gets its (still empty) matches
    right away, so the bracket can be shown before qualifiers are known."""
    # Ensure the newly created stage row exists before inserting
    # structure-only matches that reference its `stage_id`.
    db.session.flush()

    pending_specs_result = _build_pending_structure_match_specs_for_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=main_stage_size,
    )
    if pending_specs_result.is_err():
        return Err(pending_specs_result.unwrap_err())

    _persist_generated_matches(
        tournament_id=tournament_id,
        stage_id=main_stage.id,
        specs=pending_specs_result.unwrap(),
    )
    return Ok(None)
