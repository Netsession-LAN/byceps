"""
byceps.services.netsession_tourney.qualifier_selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants of a stage that qualified in earlier (source) stages: the best
of each match, of each source stage, or of each group.
"""

from __future__ import annotations

from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .dbmodels import DbNetsessionTourneyStage
from .models import Participant, ParticipantID, Stage, TournamentID
from .qualifier_ranking import (
    get_effective_qualifier_top_n_for_source_stage,
    get_ranked_participant_ids_by_group_for_stage,
)
from .qualifier_selection_parts import (
    _get_qualifier_top_n_per_match,
    _get_source_stage_ids,
    _load_source_stages,
    _participants_in_order,
    _require_enough_qualified,
    _select_top_per_match_of_stages,
    _source_stage_error,
)
from .stage_ranking import get_ranked_participant_ids_for_stage


def select_match_qualifiers(
    party_id: PartyID, tournament_id: TournamentID, stage: Stage
) -> Result[list[Participant], str]:
    """The best `qualifier_top_n_per_match` of every match of the source
    stages."""
    source_stage_ids_result = _get_source_stage_ids(stage)
    if source_stage_ids_result.is_err():
        return Err(source_stage_ids_result.unwrap_err())

    top_n_per_match_result = _get_qualifier_top_n_per_match(stage)
    if top_n_per_match_result.is_err():
        return Err(top_n_per_match_result.unwrap_err())
    top_n_per_match = top_n_per_match_result.unwrap()

    source_stages_result = _load_source_stages(
        tournament_id, source_stage_ids_result.unwrap()
    )
    if source_stages_result.is_err():
        return Err(source_stages_result.unwrap_err())

    selected_participant_ids_result = _select_top_per_match_of_stages(
        source_stages_result.unwrap(), tournament_id, top_n_per_match
    )
    if selected_participant_ids_result.is_err():
        return Err(selected_participant_ids_result.unwrap_err())

    participants = domain_service.select_ready_participants(
        _participants_in_order(
            party_id, selected_participant_ids_result.unwrap()
        )
    )
    return _require_enough_qualified(participants)


def select_stage_qualifiers(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage: Stage,
    *,
    is_stage_builder_v1_stage: bool,
) -> Result[list[Participant], str]:
    """The best of each source stage, or of each of its groups."""
    source_stage_ids_result = _get_source_stage_ids(stage)
    if source_stage_ids_result.is_err():
        return Err(source_stage_ids_result.unwrap_err())

    selection_mode_result = _get_qualifier_selection_mode(stage)
    if selection_mode_result.is_err():
        return Err(selection_mode_result.unwrap_err())
    selection_mode = selection_mode_result.unwrap()

    source_stages_result = _load_source_stages(
        tournament_id, source_stage_ids_result.unwrap()
    )
    if source_stages_result.is_err():
        return Err(source_stages_result.unwrap_err())

    selected_participant_ids_result = _select_top_of_stages(
        stage, source_stages_result.unwrap(), tournament_id, selection_mode
    )
    if selected_participant_ids_result.is_err():
        return Err(selected_participant_ids_result.unwrap_err())

    participants = _participants_in_order(
        party_id, list(dict.fromkeys(selected_participant_ids_result.unwrap()))
    )
    participants = _select_qualified_ready_participants(
        participants, is_stage_builder_v1_stage=is_stage_builder_v1_stage
    )
    return _require_enough_qualified(participants)


def _get_qualifier_selection_mode(stage: Stage) -> Result[str, str]:
    selection_mode = (stage.settings or {}).get(
        'qualifier_selection_mode', 'per_stage'
    )
    if selection_mode not in {'per_stage', 'per_group'}:
        return Err('Ungültige Auswahl der Qualifikanten.')
    return Ok(selection_mode)


def _select_top_of_stages(
    stage: Stage,
    db_source_stages: list[DbNetsessionTourneyStage],
    tournament_id: TournamentID,
    selection_mode: str,
) -> Result[list[ParticipantID], str]:
    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in db_source_stages:
        top_n_result = get_effective_qualifier_top_n_for_source_stage(
            stage, db_source_stage, tournament_id, selection_mode=selection_mode
        )
        if top_n_result.is_err():
            return Err(
                f'Quellphase „{db_source_stage.name}“: {top_n_result.unwrap_err()}'
            )

        pick_qualifiers = (
            _select_top_per_group
            if selection_mode == 'per_group'
            else _select_top_of_stage
        )
        ids_result = pick_qualifiers(
            db_source_stage, tournament_id, top_n_result.unwrap()
        )
        if ids_result.is_err():
            return Err(ids_result.unwrap_err())
        selected_participant_ids.extend(ids_result.unwrap())
    return Ok(selected_participant_ids)


def _select_qualified_ready_participants(
    participants: list[Participant], *, is_stage_builder_v1_stage: bool
) -> list[Participant]:
    if is_stage_builder_v1_stage:
        return domain_service.select_ready_participants(participants)

    return domain_service.select_bracket_ready_participants(participants)


def _select_top_per_group(
    db_source_stage, tournament_id, top_n: int
) -> Result[list[ParticipantID], str]:
    groups_result = get_ranked_participant_ids_by_group_for_stage(
        db_source_stage.id, tournament_id
    )
    if groups_result.is_err():
        return _source_stage_error(db_source_stage, groups_result.unwrap_err())

    selected: list[ParticipantID] = []
    for ranked_group_participant_ids in groups_result.unwrap():
        if len(ranked_group_participant_ids) < top_n:
            return Err(
                f'Quellphase „{db_source_stage.name}“ hat eine Gruppe mit '
                f'nur {len(ranked_group_participant_ids)} gewerteten '
                f'Teilnehmern, gebraucht werden aber die Top {top_n} pro Gruppe.'
            )
        selected.extend(ranked_group_participant_ids[:top_n])
    return Ok(selected)


def _select_top_of_stage(
    db_source_stage, tournament_id, top_n: int
) -> Result[list[ParticipantID], str]:
    ranked_result = get_ranked_participant_ids_for_stage(
        db_source_stage.id, tournament_id
    )
    if ranked_result.is_err():
        return _source_stage_error(db_source_stage, ranked_result.unwrap_err())

    ranked_participant_ids = ranked_result.unwrap()
    if len(ranked_participant_ids) < top_n:
        return Err(
            f'Quellphase „{db_source_stage.name}“ hat nur '
            f'{len(ranked_participant_ids)} gewertete Teilnehmer, '
            f'gebraucht werden aber die Top {top_n}.'
        )
    return Ok(ranked_participant_ids[:top_n])
