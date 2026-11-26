"""
byceps.services.netsession_tourney.blueprints.site.builder_display_summary_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Summary lines for builder stages whose matches are not generated yet.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .builder_helpers import (
    get_builder_container_child_stages,
)


def build_builder_stage_summary_lines(stage, stages) -> list[str]:
    settings = stage.settings or {}
    if settings.get('builder_materialized_stage_ids'):
        return _build_round_container_summary_lines(stage, stages)

    return _build_group_summary_lines(stage, stages, settings)


def _build_round_container_summary_lines(stage, stages) -> list[str]:
    lines = [
        gettext(
            'Diese Vorrunden-Übersicht enthält eigene Rundenphasen, die nacheinander vorbereitet und gespielt werden.'
        )
    ]
    child_stages = get_builder_container_child_stages(stages, stage)
    if child_stages:
        lines.append(
            gettext(
                '%(count)s Rundenphasen: %(names)s',
                count=len(child_stages),
                names=', '.join(stage_item.name for stage_item in child_stages),
            )
        )

    _append_main_stage_line(lines, stage, stages)
    return lines


def _build_group_summary_lines(stage, stages, settings) -> list[str]:
    lines = [
        gettext(
            'Diese Vorrunden-Übersicht fasst die Gruppenphase zusammen. Die eigentlichen Matches liegen in den Gruppenphasen.'
        )
    ]

    group_stages = _get_summary_group_stages(stages, settings)
    if group_stages:
        lines.append(
            gettext(
                '%(count)s Gruppenphasen: %(names)s',
                count=len(group_stages),
                names=', '.join(stage_item.name for stage_item in group_stages),
            )
        )

    qualifier_top_n = settings.get('builder_materialized_qualifiers_per_group')
    if qualifier_top_n:
        lines.append(
            gettext(
                'Qualifikation: Top %(top_n)s pro Gruppe ins Hauptturnier.',
                top_n=qualifier_top_n,
            )
        )

    _append_main_stage_line(lines, stage, stages)
    return lines


def _get_summary_group_stages(stages, settings) -> list:
    group_stage_ids = {
        str(stage_id)
        for stage_id in settings.get('builder_materialized_group_stage_ids', [])
    }
    return [
        stage_item
        for stage_item in stages
        if str(stage_item.id) in group_stage_ids
    ]


def _append_main_stage_line(lines: list[str], stage, stages) -> None:
    main_stage = _find_main_stage_for_preliminary(stage, stages)
    if main_stage is not None:
        lines.append(gettext('Hauptturnier: %(name)s', name=main_stage.name))


def _find_main_stage_for_preliminary(stage, stages):
    return next(
        (
            stage_item
            for stage_item in stages
            if (stage_item.settings or {}).get('builder_role') == 'main'
            and (stage_item.settings or {}).get('builder_preliminary_stage_id')
            == str(stage.id)
        ),
        None,
    )
