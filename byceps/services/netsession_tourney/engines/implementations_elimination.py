"""
byceps.services.netsession_tourney.engines.implementations_elimination
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Single and double elimination engines.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.models import (
    MatchID,
    ParticipantID,
    Stage,
    TournamentMode,
)
from byceps.util.result import Err, Ok, Result

from .base import MatchSpec, StageEngine
from .bracket_helpers import (
    build_double_elimination_specs,
    build_single_elimination_specs,
)
from .bracket_helpers_slots import (
    build_seeded_bracket_slots,
    seeded_slots,
    sourced_slot,
    with_computed_round_numbers,
)
from .implementations_mixins import (
    _AtLeastTwoParticipantsMixin,
    _ScoreStandingsMixin,
    _SortedScoreStandingsMixin,
    _WinnerMovesOnMixin,
)


class _SingleEliminationEngine(_SortedScoreStandingsMixin, StageEngine):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        bracket_slots = build_seeded_bracket_slots(participant_ids)
        include_consolation_final = len(participant_ids) >= 4 and bool(
            stage.settings.get('include_consolation_final', True)
        )

        return Ok(
            build_single_elimination_specs(
                bracket_slots,
                include_consolation_final=include_consolation_final,
            )
        )

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage
        updates: list[tuple[MatchID, int, ParticipantID | None]] = []
        if winner_id is None:
            return updates

        for match_id, slot_no in downstream_slots:
            updates.append((match_id, slot_no, winner_id))
        return updates


class _DoubleEliminationEngine(
    _AtLeastTwoParticipantsMixin,
    _WinnerMovesOnMixin,
    _ScoreStandingsMixin,
    StageEngine,
):
    mode = TournamentMode.duel

    def __init__(self, *, include_double_grand_final: bool = False) -> None:
        self._include_double_grand_final = include_double_grand_final

    def _generate_for_two(self, bracket_slots) -> list[MatchSpec]:
        """Two participants: the loser of match 1 gets a second chance in a
        grand final (rematch); the double grand final variant adds a reset
        match, skipped if the winner of match 1 also wins the grand final."""
        p1 = bracket_slots[0]
        p2 = bracket_slots[1] if len(bracket_slots) > 1 else None
        specs = {
            1: (seeded_slots(p1, p2), 'ready' if p1 and p2 else 'pending'),
            2: (
                [sourced_slot(1, 1, 'winner'), sourced_slot(2, 1, 'loser')],
                'pending',
            ),
        }
        if self._include_double_grand_final:
            specs[3] = (
                [sourced_slot(1, 2, 'winner'), sourced_slot(2, 2, 'loser')],
                'pending',
            )
        return with_computed_round_numbers(specs)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        bracket_slots = build_seeded_bracket_slots(participant_ids)
        bracket_size = len(bracket_slots)

        if bracket_size <= 2:
            return Ok(self._generate_for_two(bracket_slots))

        return Ok(
            build_double_elimination_specs(
                bracket_slots,
                include_double_grand_final=self._include_double_grand_final,
            )
        )
