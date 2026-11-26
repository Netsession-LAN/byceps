"""
byceps.services.netsession_tourney.stage_generation_previews
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Data and helpers for the match generation preview of a stage.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .engines.base import MatchSpec
from .generation_participants import (
    StageMatchGenerationPreviewParticipant,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
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


def _count_matches_per_round(match_specs: list[MatchSpec]) -> dict[int, int]:
    round_match_counts: dict[int, int] = defaultdict(int)
    for spec in match_specs:
        round_match_counts[spec.round_no] += 1
    return round_match_counts


def _build_generated_match_previews_by_round_no(
    match_specs: list[MatchSpec], participants: list[Participant]
) -> dict[int, list[StageGeneratedMatchPreview]]:
    preview_participants_by_id = {
        participant.id: participant for participant in participants
    }
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]] = (
        defaultdict(list)
    )
    for spec in sorted(
        match_specs, key=lambda item: (item.round_no, item.match_no)
    ):
        matches_by_round_no[spec.round_no].append(
            _build_generated_match_preview(spec, preview_participants_by_id)
        )
    return matches_by_round_no


def _build_generated_match_preview(
    spec: MatchSpec,
    preview_participants_by_id: dict[ParticipantID, Participant],
) -> StageGeneratedMatchPreview:
    return StageGeneratedMatchPreview(
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


def _build_round_generation_previews(
    round_match_counts: dict[int, int],
    suggested_round_starts_at: dict[int, datetime],
    display_titles_by_round_no: dict[int, str],
) -> list[StageRoundGenerationPreview]:
    return [
        StageRoundGenerationPreview(
            round_no=round_no,
            match_count=round_match_counts[round_no],
            suggested_starts_at=suggested_round_starts_at.get(round_no),
            display_title=display_titles_by_round_no.get(round_no),
        )
        for round_no in sorted(round_match_counts.keys())
    ]
