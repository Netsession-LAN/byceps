"""
byceps.services.netsession_tourney.stage_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match generation of a stage: payload and preview (round titles, pairings).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .double_grand_final import (
    _is_loser_source_outcome,
)
from .engines.base import MatchSpec
from .engines.registry import (
    find_stage_engine,
    get_stage_type_spec,
)
from .flatout2_builder import (
    _build_flatout2_stage_generation_payload,
    _build_manual_flatout2_stage_generation_payload,
)
from .generation_participants import (
    _order_participants_for_stage_generation,
    _select_generation_participants_for_stage,
    StageMatchGenerationPreviewParticipant,
)
from .match_schedule import (
    _build_round_starts_at_schedule,
)
from .models import (
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .registration_validation import (
    _validate_bracket_ready_team_sizes,
)
from .service_helpers import (
    _db_stage_to_model,
    _db_tournament_to_model,
)
from .stage_builder_preview import (
    _resolve_stage_builder_stage_for_generation,
)
from .stage_generation_base import (
    _StageGenerationPayload,
)
from .swiss_stage import (
    _build_swiss_stage_generation_payload,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


@dataclass(frozen=True, kw_only=True)
class StageRoundGenerationPreview:
    round_no: int
    match_count: int
    suggested_starts_at: datetime | None
    display_title: str | None = None


@dataclass(frozen=True, kw_only=True)
class StageGeneratedMatchPreview:
    round_no: int
    match_no: int
    participants: list[StageMatchGenerationPreviewParticipant]


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreview:
    stage: Stage
    participant_count: int
    match_count: int
    rounds: list[StageRoundGenerationPreview]
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]]


def preview_stage_match_generation(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[StageMatchGenerationPreview, str]:
    payload_result = _build_stage_generation_payload(
        party_id,
        tournament_id,
        stage_id,
        require_flatout2_hosts=False,
    )
    if payload_result.is_err():
        return Err(payload_result.unwrap_err())
    payload = payload_result.unwrap()

    round_match_counts: dict[int, int] = defaultdict(int)
    for spec in payload.match_specs:
        round_match_counts[spec.round_no] += 1

    suggested_round_starts_at = _build_round_starts_at_schedule(
        tournament_starts_at=payload.tournament.starts_at,
        stage=payload.stage,
        round_match_counts=round_match_counts,
    )
    display_titles_by_round_no = _build_generation_preview_round_titles_by_round_no(
        payload.stage,
        payload.match_specs,
    )
    preview_participants_by_id = {
        participant.id: participant for participant in payload.participants
    }
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]] = (
        defaultdict(list)
    )
    for spec in sorted(payload.match_specs, key=lambda item: (item.round_no, item.match_no)):
        matches_by_round_no[spec.round_no].append(
            StageGeneratedMatchPreview(
                round_no=spec.round_no,
                match_no=spec.match_no,
                participants=[
                    StageMatchGenerationPreviewParticipant(
                        participant_id=slot.participant_id,
                        name=preview_participants_by_id[slot.participant_id].name,
                    )
                    for slot in spec.slots
                    if slot.participant_id is not None
                    and slot.participant_id in preview_participants_by_id
                ],
            )
        )
    rounds = [
        StageRoundGenerationPreview(
            round_no=round_no,
            match_count=round_match_counts[round_no],
            suggested_starts_at=suggested_round_starts_at.get(round_no),
            display_title=display_titles_by_round_no.get(round_no),
        )
        for round_no in sorted(round_match_counts.keys())
    ]

    return Ok(
        StageMatchGenerationPreview(
            stage=payload.stage,
            participant_count=len(payload.participants),
            match_count=len(payload.match_specs),
            rounds=rounds,
            matches_by_round_no=dict(matches_by_round_no),
        )
    )


def _build_generation_preview_round_titles_by_round_no(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    builder_display_title = str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()
    if builder_display_title:
        round_nos = sorted({spec.round_no for spec in match_specs})
        return {round_no: builder_display_title for round_no in round_nos}

    if stage.type == StageType.ffa_flatout2_single_elimination:
        raw_rounds = (stage.settings or {}).get('flatout2_rounds')
        if isinstance(raw_rounds, list):
            titles_by_round_no: dict[int, str] = {}
            for raw_round in raw_rounds:
                if not isinstance(raw_round, dict):
                    continue
                try:
                    round_no = int(raw_round.get('round_no') or 0)
                except (TypeError, ValueError):
                    continue
                if round_no < 1:
                    continue
                display_title = str(
                    raw_round.get('display_title')
                    or raw_round.get('title')
                    or ''
                ).strip()
                if display_title:
                    titles_by_round_no[round_no] = display_title
            if titles_by_round_no:
                return titles_by_round_no

        round_nos = sorted({spec.round_no for spec in match_specs})
        try:
            total_round_count = int((stage.settings or {}).get('round_count') or 0)
        except (TypeError, ValueError):
            total_round_count = 0

        return {
            round_no: (
                'Finale'
                if total_round_count > 0 and round_no == total_round_count
                else f'Runde {round_no}'
            )
            for round_no in round_nos
        }

    if stage.type not in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return {}

    specs_by_match_no = {
        spec.match_no: spec
        for spec in sorted(match_specs, key=lambda item: (item.round_no, item.match_no))
    }
    bracket_by_match_no: dict[int, str] = {}

    changed = True
    while changed:
        changed = False
        for spec in specs_by_match_no.values():
            incoming = [
                (slot.source_match_no, slot.source_outcome)
                for slot in spec.slots
                if slot.source_match_no is not None
            ]
            bracket = bracket_by_match_no.get(spec.match_no)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                source_brackets = {
                    bracket_by_match_no.get(source_match_no)
                    for source_match_no, _ in incoming
                }
                source_brackets.discard(None)

                if 'GF' in source_brackets:
                    next_bracket = 'GF'
                elif any(_is_loser_source_outcome(outcome) for _, outcome in incoming):
                    next_bracket = 'LB'
                elif source_brackets == {'WB'}:
                    next_bracket = 'WB'
                elif source_brackets == {'LB'}:
                    next_bracket = 'LB'
                elif source_brackets == {'WB', 'LB'}:
                    next_bracket = 'GF'

            if next_bracket != bracket:
                bracket_by_match_no[spec.match_no] = next_bracket
                changed = True

    round_nos_by_bracket: dict[str, list[int]] = defaultdict(list)
    brackets_by_round_no: dict[int, set[str]] = defaultdict(set)
    for spec in specs_by_match_no.values():
        bracket = bracket_by_match_no.get(spec.match_no)
        if bracket is None:
            continue
        if spec.round_no not in round_nos_by_bracket[bracket]:
            round_nos_by_bracket[bracket].append(spec.round_no)
        brackets_by_round_no[spec.round_no].add(bracket)

    title_by_round_no: dict[int, str] = {}

    wb_titles = {
        round_no: _get_generation_preview_winner_round_title(
            index, len(round_nos_by_bracket['WB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['WB']))
    }
    lb_titles = {
        round_no: _get_generation_preview_loser_round_title(
            index, len(round_nos_by_bracket['LB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['LB']))
    }
    gf_titles = {}
    sorted_gf_round_nos = sorted(round_nos_by_bracket['GF'])
    for index, round_no in enumerate(sorted_gf_round_nos):
        gf_titles[round_no] = (
            'Grand Final'
            if index == 0
            else 'Double Grand Final'
            if index == 1
            else f'Grand Final {index + 1}'
        )

    for round_no in sorted(brackets_by_round_no):
        parts = []
        if round_no in wb_titles:
            parts.append(wb_titles[round_no])
        if round_no in lb_titles:
            parts.append(lb_titles[round_no])
        if round_no in gf_titles:
            parts.append(gf_titles[round_no])
        if parts:
            title_by_round_no[round_no] = ' + '.join(parts)

    return title_by_round_no


def _get_generation_preview_winner_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Winner Bracket Final'
    if round_index == round_count - 2:
        return 'Winner Bracket Semi-Final'
    return f'Winner Bracket Round {round_index + 1}'


def _get_generation_preview_loser_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Loser Bracket Final'
    if round_count >= 3 and round_index == round_count - 2:
        return 'Loser Bracket Semi-Final'
    return f'Loser Bracket Round {round_index + 1}'


def _build_stage_generation_payload(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    *,
    stage_settings_override: dict[str, Any] | None = None,
    require_flatout2_hosts: bool = True,
) -> Result[_StageGenerationPayload, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    stage = _db_stage_to_model(db_stage)
    if stage_settings_override:
        merged_stage_settings = dict(stage.settings or {})
        merged_stage_settings.update(stage_settings_override)
        stage = replace(stage, settings=merged_stage_settings)
    tournament = _db_tournament_to_model(db_tournament)
    stage_type_spec = get_stage_type_spec(stage.type)
    if not stage_type_spec.enabled:
        return Err('Dieser Stage-Typ ist zurzeit deaktiviert.')

    engine = find_stage_engine(stage.type)
    if engine is None:
        return Err('Für diesen Stage-Typ gibt es noch keine Match-Erzeugung.')

    selected_participants_result = _select_generation_participants_for_stage(
        party_id,
        tournament_id,
        stage,
    )
    if selected_participants_result.is_err():
        return Err(selected_participants_result.unwrap_err())
    participants = selected_participants_result.unwrap()

    team_size_validation_result = _validate_bracket_ready_team_sizes(
        tournament, participants
    )
    if team_size_validation_result.is_err():
        return Err(team_size_validation_result.unwrap_err())

    ordered_participants = _order_participants_for_stage_generation(
        participants,
        shuffle_unseeded=(
            (stage.settings or {}).get('participant_source_mode')
            not in {
                'stage_qualifiers',
                'stage_match_qualifiers',
                'builder_fixed_participants',
            }
        ),
    )
    participant_ids = [participant.id for participant in ordered_participants]
    resolved_stage_result = _resolve_stage_builder_stage_for_generation(
        stage,
        participant_count=len(participant_ids),
    )
    if resolved_stage_result.is_err():
        return Err(resolved_stage_result.unwrap_err())
    stage = resolved_stage_result.unwrap()

    if (
        stage.type == StageType.ffa_flatout2_single_elimination
        and (
            (stage.settings or {}).get('flatout2_manual_stage')
            or not (stage.settings or {}).get('builder_kind')
        )
    ):
        return _build_manual_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
        )

    validation_result = engine.validate(stage, participant_ids)
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return _build_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
            require_hosts=require_flatout2_hosts,
        )

    if stage.type == StageType.swiss:
        return _build_swiss_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
        )

    generation_result = engine.generate(stage, participant_ids)
    if generation_result.is_err():
        return Err(generation_result.unwrap_err())

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            match_specs=generation_result.unwrap(),
        )
    )
