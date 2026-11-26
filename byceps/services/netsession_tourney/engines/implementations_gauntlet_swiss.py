"""
byceps.services.netsession_tourney.engines.implementations_gauntlet_swiss
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Gauntlet and Swiss engines.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.models import (
    ParticipantID,
    Stage,
    TournamentMode,
)
from byceps.util.result import Err, Ok, Result

from .base import MatchSpec, SlotSpec, StageEngine
from .engine_pairings import build_swiss_specs
from .implementations_mixins import (
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
    _ScoreStandingsMixin,
    _SortedScoreStandingsMixin,
    _WinnerMovesOnMixin,
)
from .implementations_settings import (
    _get_swiss_round_count_from_settings,
    _get_swiss_threshold,
)


class _GauntletEngine(
    _AtLeastTwoParticipantsMixin,
    _WinnerMovesOnMixin,
    _ScoreStandingsMixin,
    StageEngine,
):
    mode = TournamentMode.duel

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        ordered = list(participant_ids)
        specs: list[MatchSpec] = []
        match_no = 1

        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='ready',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=ordered[0],
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=ordered[1],
                        source_match_no=None,
                    ),
                ],
            )
        )
        previous_match_no = match_no
        match_no += 1

        for index, participant_id in enumerate(ordered[2:], start=2):
            specs.append(
                MatchSpec(
                    round_no=index,
                    match_no=match_no,
                    state='pending',
                    slots=[
                        SlotSpec(
                            slot_no=1,
                            participant_id=None,
                            source_match_no=previous_match_no,
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=participant_id,
                            source_match_no=None,
                        ),
                    ],
                )
            )
            previous_match_no = match_no
            match_no += 1

        return Ok(specs)


class _SwissEngine(
    _NoAdvancementMixin, _SortedScoreStandingsMixin, StageEngine
):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')

        threshold = _get_swiss_threshold(stage.settings)
        if threshold is not None and threshold not in {2, 3, 4}:
            return Err('Swiss requires a valid threshold.')

        round_count = _get_swiss_round_count_from_settings(stage.settings)
        if round_count < 1:
            return Err('Swiss requires at least 1 round.')
        if threshold is None and round_count % 2 == 0:
            return Err(
                'Swiss braucht eine ungerade Rundenanzahl, damit die Sieg-/Niederlagen-Schwellen gleich sind.'
            )

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        round_count = _get_swiss_round_count_from_settings(stage.settings)
        return Ok(build_swiss_specs(participant_ids, round_count))
