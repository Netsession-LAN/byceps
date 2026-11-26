"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_generation_summary_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Summary lines on the generation form of a stage builder stage
(see `stage_builder_summary_lines`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines import (
    build_group_size_summary_lines,
    get_group_materialization_line,
    get_group_qualification_line,
    get_round_robin_builder_mode,
    get_round_robin_strategy_line,
)
from byceps.services.netsession_tourney.engines.bracket_helpers import (
    distribute_evenly,
)
from byceps.services.netsession_tourney.models import Stage, StageType


# generation summary


def build_preliminary_generation_summary_lines(
    stage: Stage,
    settings: dict,
    participant_count: int,
    match_count: int | None,
) -> list[str]:
    main_stage_size = settings.get('builder_main_stage_size')
    if stage.type == StageType.round_robin_groups:
        return _build_round_robin_generation_summary_lines(
            stage, settings, participant_count, match_count
        )
    if stage.type == StageType.swiss and main_stage_size:
        return [
            gettext(
                'Qualifikation: Top %(size)s insgesamt aus Swiss ins Hauptturnier',
                size=main_stage_size,
            )
        ]
    return []


def _build_round_robin_generation_summary_lines(
    stage: Stage,
    settings: dict,
    participant_count: int,
    match_count: int | None,
) -> list[str]:
    main_stage_size = settings.get('builder_main_stage_size')
    group_count = settings.get('group_count')
    qualifiers_per_group = settings.get('builder_resolved_qualifiers_per_group')

    lines = _build_round_robin_strategy_lines(
        get_round_robin_builder_mode(stage, settings), group_count
    )
    if group_count:
        lines.append(gettext('Gruppen: %(count)s', count=group_count))
    lines.extend(_build_resolved_group_size_lines(settings))
    if qualifiers_per_group and main_stage_size:
        lines.append(
            get_group_qualification_line(qualifiers_per_group, main_stage_size)
        )
    if group_count:
        lines.extend(
            build_group_size_summary_lines(
                distribute_evenly(participant_count, int(group_count))
            )
        )
    if match_count is not None:
        lines.append(
            gettext(
                '%(count)s Vorrunden-Matches insgesamt',
                count=match_count,
            )
        )
    lines.extend(_build_round_robin_generation_notes())
    return lines


def _build_round_robin_strategy_lines(
    round_robin_builder_mode, group_count
) -> list[str]:
    lines = [get_round_robin_strategy_line(round_robin_builder_mode)]
    if round_robin_builder_mode == 'manual_group_count' and group_count:
        lines.append(
            gettext(
                'Manuell vorgegeben: %(count)s Gruppen',
                count=group_count,
            )
        )
    return lines


def _build_resolved_group_size_lines(settings: dict) -> list[str]:
    min_group_size = settings.get('builder_resolved_group_size_min')
    max_group_size = settings.get('builder_resolved_group_size_max')
    if not (min_group_size and max_group_size):
        return []

    if min_group_size == max_group_size:
        return [
            gettext(
                'Gruppengröße: %(size)s Teilnehmer',
                size=min_group_size,
            )
        ]

    return [
        gettext(
            'Gruppengrößen: %(min)s bis %(max)s Teilnehmer',
            min=min_group_size,
            max=max_group_size,
        )
    ]


def _build_round_robin_generation_notes() -> list[str]:
    return [
        get_group_materialization_line(),
        gettext(
            'Die Rundentabelle darunter zeigt globale Runden über alle Gruppen. Runde 1 bedeutet die erste Spielrunde in jeder Gruppe.'
        ),
        gettext(
            'Round Count und Group Size werden bei Vorrunden des Turnierplaners aus den aktuellen bereiten Teilnehmern abgeleitet und sind deshalb nicht als feste statische Phasenwerte hinterlegt.'
        ),
    ]


def get_main_generation_summary_line(
    stage: Stage, participant_count: int, main_stage_size
) -> str:
    if not (stage.settings or {}).get('builder_preliminary_stage_id'):
        return gettext(
            'Dieses Hauptturnier wird direkt aus bereiten Teilnehmern erzeugt.'
        )

    if participant_count <= int(main_stage_size or 0):
        return gettext(
            'Die Vorrunde ist aktuell nicht nötig. Das Hauptturnier wird direkt aus den bereiten Teilnehmern erzeugt.'
        )

    return gettext(
        'Das Hauptturnier wird aus den Qualifikanten der Vorrunde gespeist.'
    )
