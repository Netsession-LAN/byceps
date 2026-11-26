"""
byceps.services.netsession_tourney.engines.implementations_ffa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Free-for-all engines (simple, knockout, FlatOut 2 knockout).

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
from .engine_ffa_knockouts import (
    build_ffa_first_round_specs,
    build_ffa_knockout_follow_up_specs,
    build_flatout2_follow_up_specs,
)
from .implementations_mixins import (
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
    _ScoreStandingsMixin,
    _SortedScoreStandingsMixin,
    _WinnerMovesOnMixin,
)
from .implementations_settings import (
    _get_max_players_per_match,
)


class _FfaSimpleEngine(
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
    _SortedScoreStandingsMixin,
    StageEngine,
):
    mode = TournamentMode.ffa

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        slots = [
            SlotSpec(
                slot_no=index + 1,
                participant_id=participant_id,
                source_match_no=None,
            )
            for index, participant_id in enumerate(participant_ids)
        ]
        return Ok(
            [
                MatchSpec(
                    round_no=1,
                    match_no=1,
                    state='ready',
                    slots=slots,
                )
            ]
        )


class _FfaKnockoutEngine(
    _WinnerMovesOnMixin, _ScoreStandingsMixin, StageEngine
):
    mode = TournamentMode.ffa

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')

        max_players = _get_max_players_per_match(stage.settings)
        if max_players < 2:
            return Err('Maximale Spieler pro Match müssen mindestens 2 sein.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        max_players = _get_max_players_per_match(stage.settings)
        specs = build_ffa_first_round_specs(participant_ids, max_players)
        specs.extend(
            build_ffa_knockout_follow_up_specs(
                [spec.match_no for spec in specs],
                first_match_no=len(specs) + 1,
                max_players=max_players,
            )
        )
        return Ok(specs)


class _Flatout2KnockoutEngine(
    _WinnerMovesOnMixin, _ScoreStandingsMixin, StageEngine
):
    mode = TournamentMode.ffa
    qualifier_count_per_match = 3
    max_supported_players_per_match = 8

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')

        max_players = _get_max_players_per_match(stage.settings)
        if max_players < self.qualifier_count_per_match * 2:
            return Err(
                'Für FlatOut 2 müssen es mindestens 6 Spieler pro Match sein.'
            )
        if max_players > self.max_supported_players_per_match:
            return Err('FlatOut 2 erlaubt höchstens 8 Spieler pro Match.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        max_players = _get_max_players_per_match(stage.settings)
        specs = build_ffa_first_round_specs(participant_ids, max_players)
        specs.extend(
            build_flatout2_follow_up_specs(
                [spec.match_no for spec in specs],
                first_match_no=len(specs) + 1,
                max_players=max_players,
                qualifier_count_per_match=self.qualifier_count_per_match,
            )
        )
        return Ok(specs)
