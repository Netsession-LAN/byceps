"""
byceps.services.netsession_tourney.engines.implementations_mixins
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mixins shared by the engine implementations: validation, advancement
and standings.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.models import (
    MatchID,
    ParticipantID,
    Stage,
)
from byceps.util.result import Err, Ok, Result

from .base import Standing


class _AtLeastTwoParticipantsMixin:
    """Any number of participants from two on."""

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)


class _WinnerMovesOnMixin:
    """The winner moves into the downstream slots."""

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage
        if winner_id is None:
            return []

        return [
            (match_id, slot_no, winner_id)
            for match_id, slot_no in downstream_slots
        ]


class _NoAdvancementMixin:
    """Nobody moves on from a match (pairings are seeded separately)."""

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage, winner_id, downstream_slots
        return []


class _ScoreStandingsMixin:
    """Standings by score."""

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _SortedScoreStandingsMixin:
    """Standings sorted by score, ranked 1..n."""

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        standings = [
            Standing(
                participant_id=participant_id,
                rank=0,
                score=match_scores.get(participant_id, 0),
            )
            for participant_id in participant_ids
        ]
        standings.sort(key=lambda item: item.score, reverse=True)
        return [
            Standing(
                participant_id=item.participant_id,
                rank=index + 1,
                score=item.score,
            )
            for index, item in enumerate(standings)
        ]


def _build_score_based_standings(
    participant_ids: list[ParticipantID],
    match_scores: dict[ParticipantID, int],
) -> list[Standing]:
    standings = [
        Standing(
            participant_id=participant_id,
            rank=0,
            score=match_scores.get(participant_id, 0),
        )
        for participant_id in participant_ids
    ]
    standings.sort(key=lambda item: item.score, reverse=True)
    return [
        Standing(
            participant_id=item.participant_id,
            rank=index + 1,
            score=item.score,
        )
        for index, item in enumerate(standings)
    ]
