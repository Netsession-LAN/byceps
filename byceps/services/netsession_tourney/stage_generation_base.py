"""
byceps.services.netsession_tourney.stage_generation_base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks of match generation shared by all stage types.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engines.base import MatchSpec, StageEngine
from .models import (
    Participant,
    Stage,
    Tournament,
)


@dataclass(frozen=True, kw_only=True)
class StageGenerationPayload:
    tournament: Tournament
    stage: Stage
    engine: StageEngine
    participants: list[Participant]
    match_specs: list[MatchSpec]
    replace_existing_matches: bool = True


def distribute_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count < 1:
        return []

    base = total // bucket_count
    remainder = total % bucket_count
    return [
        base + (1 if index < remainder else 0) for index in range(bucket_count)
    ]
