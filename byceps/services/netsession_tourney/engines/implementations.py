"""
byceps.services.netsession_tourney.engines.implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

import math
from typing import TypeVar

from byceps.util.result import Err, Ok, Result

from ..models import MatchID, ParticipantID, Stage, TournamentMode
from .base import MatchSpec, SlotSpec, StageEngine, Standing

T = TypeVar('T')


class _SingleEliminationEngine(StageEngine):
    mode = TournamentMode.duel

    def validate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[None, str]:
        if len(participant_ids) < 2:
            return Err('At least 2 participants are required.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        bracket_slots = _build_seeded_bracket_slots(participant_ids)
        bracket_size = len(bracket_slots)
        include_consolation_final = (
            len(participant_ids) >= 4
            and bool(stage.settings.get('include_consolation_final', True))
        )

        specs: list[MatchSpec] = []
        previous_round_match_numbers: list[int] = []

        round_no = 1
        match_no = 1
        first_round_matches = bracket_size // 2
        for index in range(first_round_matches):
            p1 = bracket_slots[index * 2]
            p2 = bracket_slots[index * 2 + 1]
            state = 'ready' if p1 and p2 else 'pending'

            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state=state,
                    slots=[
                        SlotSpec(
                            slot_no=1,
                            participant_id=p1,
                            source_match_no=None,
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=p2,
                            source_match_no=None,
                        ),
                    ],
                )
            )
            previous_round_match_numbers.append(match_no)
            match_no += 1

        round_no += 1
        while len(previous_round_match_numbers) > 1:
            current_round_match_numbers = []
            is_final_round = len(previous_round_match_numbers) == 2
            for index in range(0, len(previous_round_match_numbers), 2):
                source1 = previous_round_match_numbers[index]
                source2 = previous_round_match_numbers[index + 1]

                specs.append(
                    MatchSpec(
                        round_no=round_no,
                        match_no=match_no,
                        state='pending',
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=None,
                                source_match_no=source1,
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=None,
                                source_match_no=source2,
                            ),
                        ],
                    )
                )
                current_round_match_numbers.append(match_no)
                match_no += 1

            if include_consolation_final and is_final_round:
                semifinal_1, semifinal_2 = previous_round_match_numbers
                specs.append(
                    MatchSpec(
                        round_no=round_no,
                        match_no=match_no,
                        state='pending',
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=None,
                                source_match_no=semifinal_1,
                                source_outcome='loser',
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=None,
                                source_match_no=semifinal_2,
                                source_outcome='loser',
                            ),
                        ],
                    )
                )
                match_no += 1

            previous_round_match_numbers = current_round_match_numbers
            round_no += 1

        return Ok(specs)

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
            return Err('At least 2 participants are required.')
        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        bracket_slots = _build_seeded_bracket_slots(participant_ids)
        bracket_size = len(bracket_slots)

        # Degenerate case (2 participants): one duel is sufficient.
        if bracket_size <= 2:
            p1 = bracket_slots[0]
            p2 = bracket_slots[1] if len(bracket_slots) > 1 else None
            return Ok(
                [
                    MatchSpec(
                        round_no=1,
                        match_no=1,
                        state='ready' if p1 and p2 else 'pending',
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=p1,
                                source_match_no=None,
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=p2,
                                source_match_no=None,
                            ),
                        ],
                    )
                ]
            )

        specs_by_match_no: dict[int, tuple[list[SlotSpec], str]] = {}
        match_no = 1

        wb_round_match_nos: list[list[int]] = []

        # WB round 1 from seeded participants.
        wb_round_1: list[int] = []
        for index in range(0, bracket_size, 2):
            p1 = bracket_slots[index]
            p2 = bracket_slots[index + 1]
            state = 'ready' if p1 and p2 else 'pending'
            specs_by_match_no[match_no] = (
                [
                    SlotSpec(
                        slot_no=1,
                        participant_id=p1,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=p2,
                        source_match_no=None,
                    ),
                ],
                state,
            )
            wb_round_1.append(match_no)
            match_no += 1
        wb_round_match_nos.append(wb_round_1)

        # WB follow-up rounds.
        previous_wb_round = wb_round_1
        while len(previous_wb_round) > 1:
            current_wb_round: list[int] = []
            for index in range(0, len(previous_wb_round), 2):
                source_a = previous_wb_round[index]
                source_b = previous_wb_round[index + 1]
                specs_by_match_no[match_no] = (
                    [
                        SlotSpec(
                            slot_no=1,
                            participant_id=None,
                            source_match_no=source_a,
                            source_outcome='winner',
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=None,
                            source_match_no=source_b,
                            source_outcome='winner',
                        ),
                    ],
                    'pending',
                )
                current_wb_round.append(match_no)
                match_no += 1
            wb_round_match_nos.append(current_wb_round)
            previous_wb_round = current_wb_round

        if len(wb_round_match_nos) < 2:
            # Should not happen for bracket_size > 2, but keep safe.
            return Ok(
                _with_computed_round_numbers(specs_by_match_no)
            )

        # LB construction.
        lb_previous_round: list[int] = []
        wb_first_round = wb_round_match_nos[0]
        for index in range(0, len(wb_first_round), 2):
            source_a = wb_first_round[index]
            source_b = wb_first_round[index + 1]
            specs_by_match_no[match_no] = (
                [
                    SlotSpec(
                        slot_no=1,
                        participant_id=None,
                        source_match_no=source_a,
                        source_outcome='loser',
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=source_b,
                        source_outcome='loser',
                    ),
                ],
                'pending',
            )
            lb_previous_round.append(match_no)
            match_no += 1

        # Interleave remaining WB rounds into LB.
        for wb_round_index in range(1, len(wb_round_match_nos)):
            wb_round = wb_round_match_nos[wb_round_index]

            while len(lb_previous_round) > len(wb_round):
                reduced_round: list[int] = []
                for index in range(0, len(lb_previous_round), 2):
                    source_a = lb_previous_round[index]
                    source_b = lb_previous_round[index + 1]
                    specs_by_match_no[match_no] = (
                        [
                            SlotSpec(
                                slot_no=1,
                                participant_id=None,
                                source_match_no=source_a,
                                source_outcome='winner',
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=None,
                                source_match_no=source_b,
                                source_outcome='winner',
                            ),
                        ],
                        'pending',
                    )
                    reduced_round.append(match_no)
                    match_no += 1
                lb_previous_round = reduced_round

            injected_round: list[int] = []
            for index, wb_match_no in enumerate(wb_round):
                lb_match_no = lb_previous_round[index]
                specs_by_match_no[match_no] = (
                    [
                        SlotSpec(
                            slot_no=1,
                            participant_id=None,
                            source_match_no=lb_match_no,
                            source_outcome='winner',
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=None,
                            source_match_no=wb_match_no,
                            source_outcome='loser',
                        ),
                    ],
                    'pending',
                )
                injected_round.append(match_no)
                match_no += 1
            lb_previous_round = injected_round

        wb_final_match_no = wb_round_match_nos[-1][0]
        lb_final_match_no = lb_previous_round[0]

        # Grand Final #1.
        specs_by_match_no[match_no] = (
            [
                SlotSpec(
                    slot_no=1,
                    participant_id=None,
                    source_match_no=wb_final_match_no,
                    source_outcome='winner',
                ),
                SlotSpec(
                    slot_no=2,
                    participant_id=None,
                    source_match_no=lb_final_match_no,
                    source_outcome='winner',
                ),
            ],
            'pending',
        )
        grand_final_match_no = match_no
        match_no += 1

        if self._include_double_grand_final:
            # Optional bracket-reset match:
            # If the LB winner wins Grand Final #1, both participants have one
            # loss and must play once more.
            specs_by_match_no[match_no] = (
                [
                    SlotSpec(
                        slot_no=1,
                        participant_id=None,
                        source_match_no=grand_final_match_no,
                        source_outcome='winner',
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=grand_final_match_no,
                        source_outcome='loser',
                    ),
                ],
                'pending',
            )

        return Ok(_with_computed_round_numbers(specs_by_match_no))

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
            return Err('At least 2 participants are required.')
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
            return Err('At least 2 participants are required.')

        threshold = _get_swiss_threshold(stage.settings)
        if threshold is not None and threshold not in {2, 3, 4}:
            return Err('Swiss requires a valid threshold.')

        round_count = _get_swiss_round_count_from_settings(stage.settings)
        if round_count < 1:
            return Err('Swiss requires at least 1 round.')
        if threshold is None and round_count % 2 == 0:
            return Err(
                'Swiss requires an odd round count so win/loss thresholds are symmetric.'
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
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=p1,
                                source_match_no=None,
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=p2,
                                source_match_no=None,
                            ),
                        ],
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
            return Err('At least 2 participants are required.')
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
            return Err('At least 2 participants are required.')
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
            return Err('At least 2 participants are required.')
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
            return Err('At least 2 participants are required.')

        max_players = _get_max_players_per_match(stage.settings)
        if max_players < 2:
            return Err('Maximum players per match must be at least 2.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        max_players = _get_max_players_per_match(stage.settings)
        specs: list[MatchSpec] = []
        match_no = 1
        round_no = 1

        previous_round_match_nos: list[int] = []
        initial_match_count = math.ceil(len(participant_ids) / max_players)
        for chunk in _chunked_evenly(
            list(participant_ids), initial_match_count
        ):
            slots = [
                SlotSpec(
                    slot_no=index + 1,
                    participant_id=participant_id,
                    source_match_no=None,
                )
                for index, participant_id in enumerate(chunk)
            ]
            if len(slots) == 1:
                slots.append(
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=None,
                    )
                )

            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='ready' if len(chunk) >= 2 else 'pending',
                    slots=slots,
                )
            )
            previous_round_match_nos.append(match_no)
            match_no += 1

        round_no += 1
        while len(previous_round_match_nos) > 1:
            current_round_match_nos: list[int] = []
            next_round_match_count = math.ceil(
                len(previous_round_match_nos) / max_players
            )
            for source_chunk in _chunked_evenly(
                previous_round_match_nos, next_round_match_count
            ):
                qualifier_slot_counts = _distribute_evenly(
                    max_players, len(source_chunk)
                )
                slots: list[SlotSpec] = []
                slot_no = 1
                for source_match_no, qualifier_count in zip(
                    source_chunk, qualifier_slot_counts, strict=False
                ):
                    for _ in range(qualifier_count):
                        slots.append(
                            SlotSpec(
                                slot_no=slot_no,
                                participant_id=None,
                                source_match_no=source_match_no,
                            )
                        )
                        slot_no += 1

                specs.append(
                    MatchSpec(
                        round_no=round_no,
                        match_no=match_no,
                        state='pending',
                        slots=slots,
                    )
                )
                current_round_match_nos.append(match_no)
                match_no += 1

            previous_round_match_nos = current_round_match_nos
            round_no += 1

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
            return Err('At least 2 participants are required.')

        max_players = _get_max_players_per_match(stage.settings)
        if max_players < self.qualifier_count_per_match * 2:
            return Err(
                'Maximum players per match must be at least 6 for FlatOut 2.'
            )
        if max_players > self.max_supported_players_per_match:
            return Err('FlatOut 2 supports at most 8 players per match.')

        return Ok(None)

    def generate(
        self, stage: Stage, participant_ids: list[ParticipantID]
    ) -> Result[list[MatchSpec], str]:
        validation_result = self.validate(stage, participant_ids)
        if validation_result.is_err():
            return Err(validation_result.unwrap_err())

        max_players = _get_max_players_per_match(stage.settings)
        specs: list[MatchSpec] = []
        match_no = 1
        round_no = 1

        previous_round_match_nos: list[int] = []
        initial_match_count = math.ceil(len(participant_ids) / max_players)
        for chunk in _chunked_evenly(
            list(participant_ids), initial_match_count
        ):
            slots = [
                SlotSpec(
                    slot_no=index + 1,
                    participant_id=participant_id,
                    source_match_no=None,
                )
                for index, participant_id in enumerate(chunk)
            ]
            if len(slots) == 1:
                slots.append(
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=None,
                    )
                )

            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='ready' if len(chunk) >= 2 else 'pending',
                    slots=slots,
                )
            )
            previous_round_match_nos.append(match_no)
            match_no += 1

        round_no += 1
        while len(previous_round_match_nos) > 1:
            source_entries = [
                source_match_no
                for source_match_no in previous_round_match_nos
                for _ in range(self.qualifier_count_per_match)
            ]
            next_round_match_count = math.ceil(
                len(source_entries) / max_players
            )
            current_round_match_nos: list[int] = []

            for source_chunk in _chunked_evenly(
                source_entries, next_round_match_count
            ):
                slots = [
                    SlotSpec(
                        slot_no=index + 1,
                        participant_id=None,
                        source_match_no=source_match_no,
                    )
                    for index, source_match_no in enumerate(source_chunk)
                ]

                specs.append(
                    MatchSpec(
                        round_no=round_no,
                        match_no=match_no,
                        state='pending',
                        slots=slots,
                    )
                )
                current_round_match_nos.append(match_no)
                match_no += 1

            previous_round_match_nos = current_round_match_nos
            round_no += 1

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


def _chunked_evenly(items: list[T], chunk_count: int) -> list[list[T]]:
    if chunk_count <= 0:
        return []

    chunk_sizes = _distribute_evenly(len(items), chunk_count)
    chunks: list[list[T]] = []
    offset = 0
    for chunk_size in chunk_sizes:
        chunks.append(items[offset : offset + chunk_size])
        offset += chunk_size

    return [chunk for chunk in chunks if chunk]


def _distribute_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count <= 0:
        return []

    base = total // bucket_count
    remainder = total % bucket_count
    return [
        base + (1 if index < remainder else 0)
        for index in range(bucket_count)
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
                    slots=[
                        SlotSpec(
                            slot_no=1,
                            participant_id=p1,
                            source_match_no=None,
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=p2,
                            source_match_no=None,
                        ),
                    ],
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


def _build_seeded_bracket_slots(
    participant_ids: list[ParticipantID],
) -> list[ParticipantID | None]:
    sorted_participants = list(participant_ids)
    bracket_size = _next_power_of_two(len(sorted_participants))
    seed_order = _build_single_elimination_seed_positions(bracket_size)

    return [
        (
            sorted_participants[seed_no - 1]
            if seed_no <= len(sorted_participants)
            else None
        )
        for seed_no in seed_order
    ]


def _with_computed_round_numbers(
    specs_by_match_no: dict[int, tuple[list[SlotSpec], str]]
) -> list[MatchSpec]:
    round_no_by_match_no: dict[int, int] = {}

    def get_round_no(match_no: int) -> int:
        existing = round_no_by_match_no.get(match_no)
        if existing is not None:
            return existing

        slots, _ = specs_by_match_no[match_no]
        source_match_nos = [
            slot.source_match_no
            for slot in slots
            if slot.source_match_no is not None
        ]
        if not source_match_nos:
            round_no = 1
        else:
            round_no = max(get_round_no(source) for source in source_match_nos) + 1

        round_no_by_match_no[match_no] = round_no
        return round_no

    return [
        MatchSpec(
            round_no=get_round_no(match_no),
            match_no=match_no,
            slots=slots,
            state=state,
        )
        for match_no, (slots, state) in sorted(specs_by_match_no.items())
    ]


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return int(math.pow(2, math.ceil(math.log2(value))))


def _build_single_elimination_seed_positions(bracket_size: int) -> list[int]:
    if bracket_size <= 1:
        return [1]

    positions = [1, 2]
    while len(positions) < bracket_size:
        current_size = len(positions) * 2
        expanded: list[int] = []
        for position in positions:
            expanded.append(position)
            expanded.append(current_size + 1 - position)
        positions = expanded

    return positions
