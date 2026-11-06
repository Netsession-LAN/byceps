"""
byceps.services.netsession_tourney.round_robin_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: round robin preliminary groups (group count and size).
"""

from __future__ import annotations

from byceps.util.result import Err, Ok, Result

from .engines.bracket_helpers import _snake_groups
from .models import (
    Participant,
)
from .stage_builder_settings import (
    _build_group_label,
    _BuilderGroupStageSpec,
    _get_divisors,
    _RoundRobinBuilderPlan,
)


def _resolve_round_robin_builder_plan(
    *,
    participant_count: int,
    main_stage_size: int,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
) -> Result[_RoundRobinBuilderPlan, str]:
    if round_robin_builder_mode == 'manual_group_count':
        if round_robin_group_count is None:
            return Err(
                'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
            )
        return _build_round_robin_builder_plan_for_group_count(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            group_count=round_robin_group_count,
            mode='manual_group_count',
        )

    candidates: list[tuple[tuple[float, int, int], _RoundRobinBuilderPlan]] = []
    for group_count in sorted(_get_divisors(main_stage_size)):
        plan_result = _build_round_robin_builder_plan_for_group_count(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            group_count=group_count,
            mode='standard',
        )
        if plan_result.is_err():
            continue
        plan = plan_result.unwrap()

        average_group_size = participant_count / plan.group_count
        prefers_esports_default = (
            main_stage_size == 16 and plan.group_count == 8 and plan.qualifiers_per_group == 2
        )
        score = (
            0 if prefers_esports_default else 1,
            abs(average_group_size - 6),
            abs(plan.qualifiers_per_group - 2),
            -plan.group_count,
        )
        candidates.append((score, plan))

    if not candidates:
        return Err(
            'Für Round Robin Groups konnte keine sinnvolle Vorrundenverteilung gefunden werden. '
            'Wähle eine andere Main Stage Größe oder ein anderes Vorrundenformat.'
        )

    candidates.sort(key=lambda item: item[0])
    return Ok(candidates[0][1])


def _build_round_robin_builder_plan_for_group_count(
    *,
    participant_count: int,
    main_stage_size: int,
    group_count: int,
    mode: str,
) -> Result[_RoundRobinBuilderPlan, str]:
    if group_count < 2:
        return Err('Die Gruppenzahl muss mindestens 2 sein.')
    if main_stage_size % group_count != 0:
        return Err(
            'Die Gruppenzahl muss das Hauptturnier gleichmäßig füllen können.'
        )

    qualifiers_per_group = main_stage_size // group_count
    if qualifiers_per_group < 1:
        return Err('Die Gruppenzahl ist ungültig.')

    min_group_size = participant_count // group_count
    max_group_size = min_group_size + (
        1 if participant_count % group_count else 0
    )
    if min_group_size < qualifiers_per_group + 2:
        return Err(
            'Die Gruppenzahl ist für diese Teilnehmerzahl zu klein oder zu aggressiv.'
        )

    return Ok(
        _RoundRobinBuilderPlan(
            group_count=group_count,
            qualifiers_per_group=qualifiers_per_group,
            min_group_size=min_group_size,
            max_group_size=max_group_size,
            mode=mode,
        )
    )


def _build_round_robin_builder_group_stage_specs(
    participants: list[Participant],
    *,
    group_count: int,
    qualifiers_per_group: int,
) -> list[_BuilderGroupStageSpec]:
    specs: list[_BuilderGroupStageSpec] = []
    for index, group_participants in enumerate(
        _snake_groups(participants, group_count)
    ):
        specs.append(
            _BuilderGroupStageSpec(
                label=_build_group_label(index),
                participant_ids=[participant.id for participant in group_participants],
                qualifiers_per_group=qualifiers_per_group,
            )
        )

    return specs
