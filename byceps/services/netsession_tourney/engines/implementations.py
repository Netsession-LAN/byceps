"""
byceps.services.netsession_tourney.engines.implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from typing import TypeVar

from byceps.util.result import Err, Ok, Result

from ..models import MatchID, ParticipantID, Stage, TournamentMode
from .base import MatchSpec, SlotSpec, StageEngine, Standing
from .bracket_helpers import (
    _build_seeded_bracket_slots,
    _chunked_evenly,
    _seeded_slots,
    _sourced_slot,
    _with_computed_round_numbers,
    build_double_elimination_specs,
    build_single_elimination_specs,
)
from .engine_ffa_knockouts import (
    build_ffa_first_round_specs,
    build_ffa_knockout_follow_up_specs,
    build_flatout2_follow_up_specs,
)

T = TypeVar('T')


class _SingleEliminationEngine(StageEngine):
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

        bracket_slots = _build_seeded_bracket_slots(participant_ids)
        include_consolation_final = (
            len(participant_ids) >= 4
            and bool(stage.settings.get('include_consolation_final', True))
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


class _DoubleEliminationEngine(StageEngine):
    mode = TournamentMode.duel

    def __init__(self, *, include_double_grand_final: bool = False) -> None:
        self._include_double_grand_final = include_double_grand_final

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)

    def _generate_for_two(self, bracket_slots) -> list[MatchSpec]:
        """Two participants: the loser of match 1 gets a second chance in a
        grand final (rematch); the double grand final variant adds a reset
        match, skipped if the winner of match 1 also wins the grand final."""
        p1 = bracket_slots[0]
        p2 = bracket_slots[1] if len(bracket_slots) > 1 else None
        specs = {
            1: (_seeded_slots(p1, p2), 'ready' if p1 and p2 else 'pending'),
            2: ([_sourced_slot(1, 1, 'winner'), _sourced_slot(2, 1, 'loser')],
                'pending'),
        }
        if self._include_double_grand_final:
            specs[3] = (
                [_sourced_slot(1, 2, 'winner'), _sourced_slot(2, 2, 'loser')],
                'pending',
            )
        return _with_computed_round_numbers(specs)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        bracket_slots = _build_seeded_bracket_slots(participant_ids)
        bracket_size = len(bracket_slots)

        if bracket_size <= 2:
            return Ok(self._generate_for_two(bracket_slots))

        return Ok(
            build_double_elimination_specs(
                bracket_slots,
                include_double_grand_final=self._include_double_grand_final,
            )
        )

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
            (match_id, slot_no, winner_id) for match_id, slot_no in downstream_slots
        ]

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _GauntletEngine(StageEngine):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)

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
            (match_id, slot_no, winner_id) for match_id, slot_no in downstream_slots
        ]

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _SwissEngine(StageEngine):
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
        rotating: list[ParticipantID | None] = list(participant_ids)
        if len(rotating) % 2 == 1:
            rotating.append(None)

        specs: list[MatchSpec] = []
        match_no = 1
        for round_no in range(1, round_count + 1):
            for index in range(0, len(rotating), 2):
                p1 = rotating[index]
                p2 = rotating[index + 1]
                state = 'ready' if p1 and p2 else 'pending'
                specs.append(
                    MatchSpec(
                        round_no=round_no,
                        match_no=match_no,
                        state=state,
                        slots=_seeded_slots(p1, p2),
                    )
                )
                match_no += 1

            # Minimal deterministic re-pairing so byes are not stuck on
            # the same participant every round in odd-sized fields.
            if len(rotating) > 2:
                rotating = [rotating[0], rotating[-1], *rotating[1:-1]]

        return Ok(specs)

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage, winner_id, downstream_slots
        return []

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


def _get_swiss_threshold(settings: dict | None) -> int | None:
    if not isinstance(settings, dict):
        return None

    raw_value = settings.get('swiss_threshold')
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _get_swiss_round_count_from_settings(settings: dict | None) -> int:
    threshold = _get_swiss_threshold(settings)
    if threshold in {2, 3, 4}:
        return (threshold * 2) - 1

    raw_round_count = (settings or {}).get('round_count', 5)
    try:
        round_count = int(raw_round_count)
    except (TypeError, ValueError):
        return 5

    return max(1, round_count)


class _RoundRobinEngine(StageEngine):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)

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

        specs, _ = _generate_round_robin_specs(
            participant_ids,
            round_count=round_count,
            first_match_no=1,
        )
        return Ok(specs)

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage, winner_id, downstream_slots
        return []

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _RoundRobinGroupsEngine(StageEngine):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        raw_group_count = stage.settings.get('group_count')
        try:
            group_count = int(raw_group_count)
        except (TypeError, ValueError):
            group_count = 0

        if group_count > 0:
            groups = _chunked_evenly(list(participant_ids), group_count)
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
            group_specs, next_match_no = _generate_round_robin_specs(
                group,
                round_count=round_count,
                first_match_no=next_match_no,
            )
            specs.extend(group_specs)

        return Ok(specs)

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage, winner_id, downstream_slots
        return []

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _FfaSimpleEngine(StageEngine):
    mode = TournamentMode.ffa

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        del stage
        if len(participant_ids) < 2:
            return Err('Es werden mindestens 2 Teilnehmer benötigt.')
        return Ok(None)

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

    def advance(
        self,
        stage: Stage,
        winner_id: ParticipantID | None,
        downstream_slots: list[tuple[MatchID, int]],
    ) -> list[tuple[MatchID, int, ParticipantID | None]]:
        del stage, winner_id, downstream_slots
        return []

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


class _FfaKnockoutEngine(StageEngine):
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
            (match_id, slot_no, winner_id) for match_id, slot_no in downstream_slots
        ]

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


class _Flatout2KnockoutEngine(StageEngine):
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
            (match_id, slot_no, winner_id) for match_id, slot_no in downstream_slots
        ]

    def standings(
        self,
        stage: Stage,
        participant_ids: list[ParticipantID],
        match_scores: dict[ParticipantID, int],
    ) -> list[Standing]:
        del stage
        return _build_score_based_standings(participant_ids, match_scores)


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


def _chunked(items: list[T], chunk_size: int) -> list[list[T]]:
    return [
        items[index : index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _generate_round_robin_specs(
    participant_ids: list[ParticipantID],
    *,
    round_count: int,
    first_match_no: int,
) -> tuple[list[MatchSpec], int]:
    rotating: list[ParticipantID | None] = list(participant_ids)
    if len(rotating) % 2 == 1:
        rotating.append(None)

    pair_count = len(rotating) // 2
    specs: list[MatchSpec] = []
    match_no = first_match_no
    round_no = 1

    for _ in range(round_count):
        for index in range(pair_count):
            p1 = rotating[index]
            p2 = rotating[-(index + 1)]
            if p1 is None and p2 is None:
                continue

            if p1 is None:
                p1, p2 = p2, p1

            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='pending' if p2 is None else 'ready',
                    slots=_seeded_slots(p1, p2),
                )
            )
            match_no += 1

        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
        round_no += 1

    return specs, match_no


def _get_round_count(raw_value: object, *, participant_count: int) -> int:
    # Round robin with an odd participant count needs one additional round
    # because each round contains one bye.
    max_rounds = (
        participant_count
        if participant_count % 2 == 1
        else max(1, participant_count - 1)
    )
    if raw_value is None:
        return max_rounds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return max_rounds

    if parsed < 1:
        return 1

    return min(parsed, max_rounds)


def _get_group_size(raw_value: object) -> int:
    if raw_value is None:
        return 4

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 4

    return max(2, parsed)


def _get_max_players_per_match(settings: dict) -> int:
    raw = settings.get('max_players_per_match', 8)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 8

    return max(2, parsed)


