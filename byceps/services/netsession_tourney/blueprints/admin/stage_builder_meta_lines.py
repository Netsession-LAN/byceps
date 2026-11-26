"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_meta_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Meta lines on the stage builder role of a stage (see
`stage_builder_summary_lines`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.models import Stage, StageType


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
