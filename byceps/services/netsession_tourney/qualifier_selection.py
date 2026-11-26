"""
byceps.services.netsession_tourney.qualifier_selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants of a stage that qualified in earlier (source) stages: the best
of each match, of each source stage, or of each group.
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .dbmodels import DbNetsessionTourneyStage
from .models import Participant, ParticipantID, Stage, TournamentID
from .participant_admin_service import get_participants_by_ids
from .qualifier_ranking import (
    get_effective_qualifier_top_n_for_source_stage,
    get_ranked_participant_ids_by_group_for_stage,
    get_ranked_participant_ids_by_match_for_stage,
)
from .stage_ranking import get_ranked_participant_ids_for_stage
from .stage_service import parse_source_stage_ids


TOO_FEW_QUALIFIED = (
    'Zu wenige qualifizierte Teilnehmer für diese Phase. '
    'Passe die Quellphasen oder die Top-Anzahl an.'
)


def select_match_qualifiers(
    party_id: PartyID, tournament_id: TournamentID, stage: Stage
) -> Result[list[Participant], str]:
    """The best `qualifier_top_n_per_match` of every match of the source
    stages."""
    source_stage_ids_result = _get_source_stage_ids(stage)
    if source_stage_ids_result.is_err():
        return Err(source_stage_ids_result.unwrap_err())

    try:
        top_n_per_match = int(
            (stage.settings or {}).get('qualifier_top_n_per_match') or 0
        )
    except TypeError, ValueError:
        top_n_per_match = 0
    if top_n_per_match < 1 or top_n_per_match > 16:
        return Err('Ungültige Top-Anzahl pro Match für die Qualifikation.')

    source_stages_result = _load_source_stages(
        tournament_id, source_stage_ids_result.unwrap()
    )
    if source_stages_result.is_err():
        return Err(source_stages_result.unwrap_err())

    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in source_stages_result.unwrap():
        ranked_result = get_ranked_participant_ids_by_match_for_stage(
            db_source_stage.id, tournament_id, top_n_per_match=top_n_per_match
        )
        if ranked_result.is_err():
            return _source_stage_error(
                db_source_stage, ranked_result.unwrap_err()
            )
        selected_participant_ids.extend(ranked_result.unwrap())

    participants = domain_service.select_ready_participants(
        _participants_in_order(party_id, selected_participant_ids)
    )
    if len(participants) < 2:
        return Err(TOO_FEW_QUALIFIED)

    return Ok(participants)


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

    selection_mode = (stage.settings or {}).get(
        'qualifier_selection_mode', 'per_stage'
    )
    if selection_mode not in {'per_stage', 'per_group'}:
        return Err('Ungültige Auswahl der Qualifikanten.')

    source_stages_result = _load_source_stages(
        tournament_id, source_stage_ids_result.unwrap()
    )
    if source_stages_result.is_err():
        return Err(source_stages_result.unwrap_err())

    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in source_stages_result.unwrap():
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

    participants = _participants_in_order(
        party_id, list(dict.fromkeys(selected_participant_ids))
    )
    participants = (
        domain_service.select_ready_participants(participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(participants)
    )
    if len(participants) < 2:
        return Err(TOO_FEW_QUALIFIED)

    return Ok(participants)


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


def _get_source_stage_ids(stage: Stage) -> Result[list, str]:
    source_stage_ids = parse_source_stage_ids(
        (stage.settings or {}).get('qualifier_source_stage_ids', [])
    )
    if not source_stage_ids:
        return Err(
            'Keine Quellphasen eingestellt. Bitte zuerst die Quellphasen '
            'für die Qualifikation festlegen.'
        )
    if stage.id in source_stage_ids:
        return Err(
            'Eine Phase kann nicht ihre eigene Quelle für Qualifikanten sein.'
        )
    return Ok(source_stage_ids)


def _load_source_stages(
    tournament_id: TournamentID, source_stage_ids: list
) -> Result[list[DbNetsessionTourneyStage], str]:
    unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
    db_source_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    if len(db_source_stages) != len(unique_source_stage_ids):
        return Err(
            'Mindestens eine der eingestellten Quellphasen existiert nicht.'
        )
    return Ok(list(db_source_stages))


def _source_stage_error(db_source_stage, message: str) -> Err:
    if message.endswith('is not fully completed yet.'):
        message = (
            'ist noch nicht vollständig abgeschlossen. '
            'Schließe zuerst alle Vorrunden-Matches ab.'
        )
    return Err(f'Quellphase „{db_source_stage.name}“: {message}')


def _participants_in_order(
    party_id: PartyID, participant_ids: list[ParticipantID]
) -> list[Participant]:
    participants_by_id = get_participants_by_ids(party_id, set(participant_ids))
    return [
        participants_by_id[participant_id]
        for participant_id in participant_ids
        if participant_id in participants_by_id
    ]
