"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_meta
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Meta box, generation summary and preview meta of stage builder
stages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_generation_summary_lines import (
    build_preliminary_generation_summary_lines,
    get_main_generation_summary_line,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_meta_lines import (
    build_stage_builder_role_meta,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display import (
    _is_stage_builder_v1_stage,
    is_builder_round_robin_summary_stage,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines import (
    format_group_distribution_summary,
    get_round_robin_builder_mode,
)
from byceps.services.netsession_tourney.engines.bracket_helpers import (
    distribute_evenly,
)
from byceps.services.netsession_tourney.models import (
    Stage,
    TournamentID,
)
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.party.models import PartyID


def build_stage_builder_meta(stage: Stage) -> dict | None:
    if not _is_stage_builder_v1_stage(stage):
        return None

    settings = stage.settings or {}
    role = settings.get('builder_role')
    main_stage_size = settings.get('builder_main_stage_size')
    generation_basis = settings.get('builder_generation_basis') or 'ready'
    lines = [
        gettext(
            'Teilnehmerbasis: %(basis)s',
            basis=(
                gettext('Bereit')
                if generation_basis == 'ready'
                else generation_basis
            ),
        )
    ]

    role_label, role_lines = build_stage_builder_role_meta(
        stage, settings, role
    )
    lines.extend(role_lines)

    if main_stage_size:
        lines.append(
            gettext('Größe des Hauptturniers: %(size)s', size=main_stage_size)
        )

    return {
        'role_label': role_label,
        'lines': lines,
    }


def build_stage_builder_generation_summary(
    stage: Stage,
    resolved_stage: Stage,
    participant_count: int,
    match_count: int | None = None,
) -> dict | None:
    if not _is_stage_builder_v1_stage(stage):
        return None

    settings = resolved_stage.settings or {}
    role = (stage.settings or {}).get('builder_role')
    main_stage_size = settings.get('builder_main_stage_size')
    lines = [
        gettext(
            'Aktuelle Generierungsbasis: %(count)s bereite Teilnehmer',
            count=participant_count,
        )
    ]

    if role == 'preliminary':
        lines.extend(
            build_preliminary_generation_summary_lines(
                stage, settings, participant_count, match_count
            )
        )
    else:
        lines.append(
            get_main_generation_summary_line(
                stage, participant_count, main_stage_size
            )
        )

    return {
        'title': gettext('Turnierplaner'),
        'lines': lines,
    }


def build_round_robin_generation_intro(
    stage: Stage,
    resolved_stage: Stage,
    participant_count: int,
) -> dict | None:
    if not is_builder_round_robin_summary_stage(stage):
        return None

    settings = resolved_stage.settings or {}
    main_stage_size = settings.get('builder_main_stage_size')
    group_count = settings.get('group_count')
    qualifiers_per_group = settings.get('builder_resolved_qualifiers_per_group')
    round_robin_builder_mode = get_round_robin_builder_mode(stage, settings)

    group_sizes: list[int] = []
    if group_count:
        group_sizes = distribute_evenly(participant_count, int(group_count))

    return {
        'is_manual_mode': round_robin_builder_mode == 'manual_group_count',
        'distribution_summary': (
            format_group_distribution_summary(group_sizes)
            if group_sizes
            else None
        ),
        'qualification_summary': _build_round_robin_qualification_summary(
            qualifiers_per_group, main_stage_size
        ),
    }


def _build_round_robin_qualification_summary(
    qualifiers_per_group, main_stage_size
) -> str | None:
    if not (qualifiers_per_group and main_stage_size):
        return None

    return gettext(
        'Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
        top_n=qualifiers_per_group,
        size=main_stage_size,
    )


def build_stage_builder_container_preview_meta(
    party_id: PartyID, tournament_id: TournamentID, stage: Stage
) -> dict | None:
    if not is_builder_round_robin_summary_stage(stage):
        return None

    preview_result = preview_stage_match_generation(
        party_id, tournament_id, stage.id
    )
    if preview_result.is_err():
        return None

    preview = preview_result.unwrap()
    intro = build_round_robin_generation_intro(
        stage,
        preview.stage,
        preview.participant_count,
    )
    if intro is None:
        return None

    return {
        'participant_count': preview.participant_count,
        'distribution_summary': intro.get('distribution_summary'),
        'qualification_summary': intro.get('qualification_summary'),
    }
