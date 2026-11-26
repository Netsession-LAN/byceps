"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Text lines that describe stages of the stage builder (Turnierplaner):
the meta box of a stage and the summary shown before generating it (see
`stage_builder_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.engines.bracket_helpers import (
    distribute_evenly,
)
from byceps.services.netsession_tourney.models import Stage, StageType


# group summaries


def format_group_distribution_summary(group_sizes: list[int]) -> str:
    if not group_sizes:
        return gettext('Keine Gruppenverteilung verfügbar.')

    counts_by_size: dict[int, int] = {}
    for size in group_sizes:
        counts_by_size[size] = counts_by_size.get(size, 0) + 1

    parts = [
        gettext('%(count)s Gruppen à %(size)s', count=count, size=size)
        for size, count in sorted(counts_by_size.items(), reverse=True)
    ]
    return gettext('Konkrete Verteilung: %(parts)s', parts=', '.join(parts))


def format_round_robin_global_round_summary(
    group_sizes: list[int],
) -> str | None:
    if not group_sizes:
        return None

    matches_by_round = _count_matches_by_round(group_sizes)
    if not matches_by_round:
        return None

    parts = [
        gettext(
            'Runde %(round_no)s: %(match_count)s Matches',
            round_no=round_index + 1,
            match_count=match_count,
        )
        for round_index, match_count in enumerate(matches_by_round)
    ]
    return gettext('Globale Rundensicht: %(parts)s', parts=', '.join(parts))


def _count_matches_by_round(group_sizes: list[int]) -> list[int]:
    matches_by_round: list[int] = []
    for group_size in group_sizes:
        round_count = (
            group_size if group_size % 2 == 1 else max(1, group_size - 1)
        )
        matches_per_round = group_size // 2
        for round_index in range(round_count):
            if round_index >= len(matches_by_round):
                matches_by_round.append(0)
            matches_by_round[round_index] += matches_per_round
    return matches_by_round


def build_group_size_summary_lines(group_sizes: list[int]) -> list[str]:
    lines = [format_group_distribution_summary(group_sizes)]
    round_summary = format_round_robin_global_round_summary(group_sizes)
    if round_summary is not None:
        lines.append(round_summary)
    return lines


def get_round_robin_builder_mode(stage: Stage, settings: dict):
    return settings.get('builder_round_robin_mode') or (
        stage.settings or {}
    ).get('builder_round_robin_mode')


def get_round_robin_strategy_line(round_robin_builder_mode) -> str:
    if round_robin_builder_mode == 'manual_group_count':
        return gettext('Strategie: Expertenoption mit manueller Gruppenzahl')

    return gettext(
        'Strategie: Empfohlener Standard, bevorzugt 8 Gruppen / Top 2 bei einem Hauptturnier mit 16 Plätzen'
    )


def get_group_materialization_line() -> str:
    return gettext(
        'Beim Erzeugen werden daraus echte Gruppenphasen wie "Vorrunde Gruppe A", "Vorrunde Gruppe B" usw.'
    )


def get_group_qualification_line(qualifiers_per_group, main_stage_size) -> str:
    return gettext(
        'Qualifikation: Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
        top_n=qualifiers_per_group,
        size=main_stage_size,
    )


# stage meta


def build_stage_builder_role_meta(
    stage: Stage, settings: dict, role
) -> tuple[str, list[str]]:
    """Return the role label and the role's lines."""
    if role == 'preliminary':
        return _build_preliminary_meta(stage, settings)
    if role == 'preliminary_round':
        return _build_preliminary_round_meta(stage, settings)
    if role == 'main_round':
        return _build_main_round_meta(stage, settings)
    if role == 'preliminary_group':
        return _build_preliminary_group_meta(settings)
    return _build_main_meta(stage, settings)


def _build_preliminary_meta(
    stage: Stage, settings: dict
) -> tuple[str, list[str]]:
    role_label = (
        gettext('Turnierplaner: Vorrunden-Übersicht')
        if stage.type == StageType.round_robin_groups
        else gettext('Turnierplaner: Vorrunde')
    )
    lines = []
    if stage.type == StageType.round_robin_groups:
        lines.extend(_build_preliminary_round_robin_meta_lines(settings))
    elif stage.type == StageType.swiss:
        lines.append(
            gettext(
                'Swiss qualifiziert über die Gesamttabelle ins Hauptturnier.'
            )
        )
    elif settings.get('builder_materialized_stage_ids'):
        lines.append(
            gettext(
                'Diese Vorrunden-Übersicht enthält eigene Rundenphasen, die nacheinander vorbereitet werden.'
            )
        )
    return role_label, lines


def _build_preliminary_round_robin_meta_lines(settings: dict) -> list[str]:
    lines = [
        gettext(
            'Diese Phase ist nur die Übersicht der Gruppenphase. Eigene Matches liegen in den Gruppenphasen.'
        ),
        gettext(
            'Round Robin Groups werden bei der Generierung gleichmäßig verteilt.'
        ),
        gettext('Qualifikation: gleich viele pro Gruppe'),
    ]
    if settings.get('builder_materialized_group_stage_ids'):
        lines.append(
            gettext(
                'Diese Übersicht wurde bereits in echte Gruppenphasen materialisiert.'
            )
        )
    return lines


def _build_preliminary_round_meta(
    stage: Stage, settings: dict
) -> tuple[str, list[str]]:
    role_label = (
        gettext('Turnierplaner')
        if stage.type == StageType.ffa_flatout2_single_elimination
        else gettext(
            'Turnierplaner: Vorrunde %(title)s',
            title=settings.get('builder_display_title') or '?',
        )
    )
    return role_label, [gettext('Teilnehmerquelle: Qualifikanten der Vorrunde')]


def _build_main_round_meta(
    stage: Stage, settings: dict
) -> tuple[str, list[str]]:
    role_label = (
        gettext('Turnierplaner')
        if stage.type == StageType.ffa_flatout2_single_elimination
        else gettext(
            'Turnierplaner: Hauptturnier %(title)s',
            title=settings.get('builder_display_title') or '?',
        )
    )
    return role_label, [gettext('Teilnehmerquelle: Qualifikanten der Vorstufe')]


def _build_preliminary_group_meta(settings: dict) -> tuple[str, list[str]]:
    role_label = gettext(
        'Turnierplaner: Vorrunden-Gruppe %(label)s',
        label=settings.get('builder_group_label') or '?',
    )
    lines = [gettext('Teilnehmerquelle: feste Gruppenzuweisung')]
    qualifier_top_n = settings.get('builder_group_qualifier_top_n')
    if qualifier_top_n:
        lines.append(
            gettext(
                'Qualifikation: Top %(top_n)s ins Hauptturnier',
                top_n=qualifier_top_n,
            )
        )
    return role_label, lines


def _build_main_meta(stage: Stage, settings: dict) -> tuple[str, list[str]]:
    role_label = (
        gettext('Turnierplaner')
        if stage.type == StageType.ffa_flatout2_single_elimination
        else gettext('Turnierplaner: Hauptturnier')
    )
    if settings.get('builder_preliminary_stage_id'):
        line = gettext('Teilnehmerquelle: automatische Qualifikation')
    else:
        line = gettext('Teilnehmerquelle: direkte bereite Teilnehmer')
    return role_label, [line]


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
