"""
byceps.services.netsession_tourney.blueprints.site.builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext


def _get_raw_builder_container_child_stage_ids(settings) -> list:
    raw_stage_ids = settings.get('builder_materialized_stage_ids') or []
    if raw_stage_ids or settings.get('builder_role') != 'preliminary':
        return raw_stage_ids

    return settings.get('builder_materialized_group_stage_ids') or []


def get_builder_container_child_stage_ids(stage) -> list[str]:
    settings = stage.settings or {}
    raw_stage_ids = _get_raw_builder_container_child_stage_ids(settings)
    return [str(stage_id) for stage_id in raw_stage_ids if stage_id]


def is_materialized_builder_container_stage(stage) -> bool:
    settings = stage.settings or {}
    return settings.get('builder_kind') == 'stage_builder_v1' and bool(
        get_builder_container_child_stage_ids(stage)
    )


def get_materialized_builder_container_stages(
    stages,
    *,
    role: str | None = None,
):
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if is_materialized_builder_container_stage(stage)
        and (role is None or (stage.settings or {}).get('builder_role') == role)
    ]


def get_builder_container_child_stages(stages, container_stage):
    child_stage_ids = set(
        get_builder_container_child_stage_ids(container_stage)
    )
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if str(stage.id) in child_stage_ids
    ]


def build_pending_builder_round_summary_lines(stage) -> list[str]:
    settings = stage.settings or {}
    source_mode = settings.get('participant_source_mode')
    if source_mode == 'stage_match_qualifiers':
        return [
            gettext(
                'Diese Runde startet, sobald die vorherige Runde abgeschlossen und die Qualifikanten übernommen wurden.'
            )
        ]
    if source_mode == 'stage_qualifiers':
        return [
            gettext(
                'Diese Runde startet, sobald die vorherige Stufe abgeschlossen ist.'
            )
        ]
    return [gettext('Diese Runde wurde noch nicht vorbereitet.')]
