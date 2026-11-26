"""
byceps.services.netsession_tourney.qualifier_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Qualifiers from a source stage: ranked participants per group or per match, and how many qualify.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyStage,
)
from .ffa_qualifiers import (
    get_ffa_single_elimination_qualifier_ids,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .qualifier_group_ranking import (
    get_ranked_participant_ids_by_group_for_stage as get_ranked_participant_ids_by_group_for_stage,
)
from .stage_builder_settings import (
    get_stage_builder_main_stage_size,
)


def get_ranked_participant_ids_by_match_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
    *,
    top_n_per_match: int,
) -> Result[list[ParticipantID], str]:
    if top_n_per_match < 1:
        return Err('ungültige Top-Anzahl pro Match.')

    db_stage = db.session.get(DbNetsessionTourneyStage, stage_id)
    if db_stage is None:
        return Err('existiert nicht.')

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id, tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    matches_error = _get_stage_matches_not_rankable_error(db_matches)
    if matches_error is not None:
        return Err(matches_error)

    ranked_participant_ids = _collect_qualifier_ids_by_match(
        db_matches, top_n_per_match
    )
    if not ranked_participant_ids:
        return Err('contains no rankable participants.')

    return Ok(ranked_participant_ids)


def _get_stage_matches_not_rankable_error(
    db_matches: list[DbNetsessionTourneyMatch],
) -> str | None:
    if not db_matches:
        return 'contains no generated matches yet.'

    if any(
        db_match.state != MatchState.completed.value for db_match in db_matches
    ):
        return 'is not fully completed yet.'

    return None


def _collect_qualifier_ids_by_match(
    db_matches: list[DbNetsessionTourneyMatch], top_n_per_match: int
) -> list[ParticipantID]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(
                [db_match.id for db_match in db_matches]
            )
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    ranked_participant_ids: list[ParticipantID] = []
    for db_match in db_matches:
        ranked_participant_ids.extend(
            get_ffa_single_elimination_qualifier_ids(
                db_match.id,
                sorted(
                    slots_by_match_id.get(db_match.id, []),
                    key=lambda db_slot: db_slot.slot_no,
                ),
                top_n_per_match,
            )
        )

    return ranked_participant_ids


def get_effective_qualifier_top_n_for_source_stage(
    stage: Stage,
    db_source_stage: DbNetsessionTourneyStage,
    tournament_id: TournamentID,
    *,
    selection_mode: str,
) -> Result[int, str]:
    if not (stage.settings or {}).get('builder_auto_qualifier_count'):
        return _get_configured_qualifier_top_n(stage)

    main_stage_size = get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Ungültige Größe des Hauptturniers im Baukasten.')

    if selection_mode == 'per_stage':
        return Ok(main_stage_size)

    return _get_auto_qualifier_top_n_per_group(
        main_stage_size, db_source_stage, tournament_id
    )


def _get_configured_qualifier_top_n(stage: Stage) -> Result[int, str]:
    raw_top_n = (stage.settings or {}).get('qualifier_top_n', 1)
    try:
        top_n = int(raw_top_n)
    except TypeError, ValueError:
        return Err('Ungültige Top-Anzahl für die Qualifikation.')
    if top_n < 1 or top_n > 128:
        return Err(
            'Die Top-Anzahl für die Qualifikation muss zwischen 1 und 128 liegen.'
        )
    return Ok(top_n)


def _get_auto_qualifier_top_n_per_group(
    main_stage_size: int,
    db_source_stage: DbNetsessionTourneyStage,
    tournament_id: TournamentID,
) -> Result[int, str]:
    if db_source_stage.type != StageType.round_robin_groups.value:
        return Err(
            'Automatische Qualifikanten pro Gruppe gibt es nur mit einer Round-Robin-Gruppenphase als Quelle.'
        )

    ranked_group_participant_ids_result = (
        get_ranked_participant_ids_by_group_for_stage(
            db_source_stage.id,
            tournament_id,
        )
    )
    if ranked_group_participant_ids_result.is_err():
        return Err(ranked_group_participant_ids_result.unwrap_err())

    ranked_groups = ranked_group_participant_ids_result.unwrap()
    return _divide_main_stage_size_among_groups(
        main_stage_size, len(ranked_groups)
    )


def _divide_main_stage_size_among_groups(
    main_stage_size: int, group_count: int
) -> Result[int, str]:
    if group_count < 1:
        return Err('enthält keine gewerteten Gruppen.')
    if main_stage_size % group_count != 0:
        return Err(
            'die Qualifikanten aus den Gruppen lassen sich nicht gleichmäßig auf die Größe des Hauptturniers verteilen.'
        )

    top_n = main_stage_size // group_count
    if top_n < 1:
        return Err('Ungültige Top-Anzahl für die Qualifikation.')

    return Ok(top_n)
