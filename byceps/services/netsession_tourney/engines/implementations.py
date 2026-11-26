"""
byceps.services.netsession_tourney.engines.implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.models import (
    ParticipantID,
    Stage,
    TournamentMode,
)
from byceps.util.result import Err, Ok, Result

from .base import MatchSpec, StageEngine
from .bracket_helpers_slots import (
    snake_groups,
)
from .engine_pairings import build_round_robin_specs
from .implementations_elimination import (
    _DoubleEliminationEngine,
    _SingleEliminationEngine,
)
from .implementations_ffa import (
    _FfaKnockoutEngine,
    _FfaSimpleEngine,
    _Flatout2KnockoutEngine,
)
from .implementations_gauntlet_swiss import (
    _GauntletEngine,
    _SwissEngine,
)
from .implementations_mixins import (
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
    _ScoreStandingsMixin,
)
from .implementations_settings import (
    _chunked,
    _get_group_size,
    _get_round_count,
)


class _RoundRobinEngine(
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
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

        round_count = _get_round_count(
            stage.settings.get('round_count'),
            participant_count=len(participant_ids),
        )

        specs, _ = build_round_robin_specs(
            participant_ids,
            round_count=round_count,
            first_match_no=1,
        )
        return Ok(specs)


class _RoundRobinGroupsEngine(
    _AtLeastTwoParticipantsMixin,
    _NoAdvancementMixin,
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

        raw_group_count = stage.settings.get('group_count')
        try:
            group_count = int(raw_group_count)
        except TypeError, ValueError:
            group_count = 0

        if group_count > 0:
            groups = snake_groups(list(participant_ids), group_count)
        else:
            group_size = _get_group_size(stage.settings.get('group_size'))
            groups = _chunked(list(participant_ids), group_size)

        specs: list[MatchSpec] = []
        next_match_no = 1
        for group in groups:
            if len(group) < 2:
                continue
            round_count = _get_round_count(
                stage.settings.get('round_count'),
                participant_count=len(group),
            )
            group_specs, next_match_no = build_round_robin_specs(
                group,
                round_count=round_count,
                first_match_no=next_match_no,
            )
            specs.extend(group_specs)

        return Ok(specs)


def get_single_elimination_engine() -> StageEngine:
    return _SingleEliminationEngine()


def get_double_elimination_engine() -> StageEngine:
    return _DoubleEliminationEngine()


def get_double_elimination_with_double_grand_final_engine() -> StageEngine:
    return _DoubleEliminationEngine(include_double_grand_final=True)


def get_swiss_engine() -> StageEngine:
    return _SwissEngine()


def get_gauntlet_engine() -> StageEngine:
    return _GauntletEngine()


def get_bracket_groups_engine() -> StageEngine:
    # Pragmatic fallback for now: single elimination style progression.
    return _SingleEliminationEngine()


def get_custom_bracket_engine() -> StageEngine:
    # Pragmatic fallback for now: single elimination style progression.
    return _SingleEliminationEngine()


def get_round_robin_groups_engine() -> StageEngine:
    return _RoundRobinGroupsEngine()


def get_league_engine() -> StageEngine:
    return _RoundRobinEngine()


def get_ffa_simple_engine() -> StageEngine:
    return _FfaSimpleEngine()


def get_ffa_single_elimination_engine() -> StageEngine:
    return _FfaKnockoutEngine()


def get_flatout2_single_elimination_engine() -> StageEngine:
    return _Flatout2KnockoutEngine()


def get_ffa_bracket_groups_engine() -> StageEngine:
    return _FfaKnockoutEngine()


def get_ffa_league_engine() -> StageEngine:
    return _FfaSimpleEngine()


def get_ffa_custom_bracket_engine() -> StageEngine:
    return _FfaKnockoutEngine()
