"""
byceps.services.netsession_tourney.engines.base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from byceps.services.netsession_tourney.models import (
    MatchID,
    ParticipantID,
    Stage,
    TournamentMode,
)
from byceps.util.result import Result


@dataclass(frozen=True, kw_only=True)
class SlotSpec:
    slot_no: int
    participant_id: ParticipantID | None
    source_match_no: int | None
    source_outcome: str = 'winner'


@dataclass(frozen=True, kw_only=True)
class MatchSpec:
    round_no: int
    match_no: int
    slots: list[SlotSpec]
    state: str


@dataclass(frozen=True, kw_only=True)
class Standing:
    participant_id: ParticipantID
    rank: int
    score: int


class StageEngine(ABC):
    mode: TournamentMode

    @abstractmethod
    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        raise NotImplementedError

    @abstractmethod
    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        raise NotImplementedError

    @abstractmethod
    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        raise NotImplementedError
