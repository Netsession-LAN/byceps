"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_review_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Text lines of the preview on the review step of the stage builder
(Turnierplaner) wizard (see `stage_builder_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_review_ffa_lines import (
    _build_ffa_lines,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines import (
    build_group_size_summary_lines,
    get_group_materialization_line,
    get_group_qualification_line,
    get_round_robin_strategy_line,
)
from byceps.services.netsession_tourney.models import StageType
from byceps.util.result import Err, Ok, Result


FFA_MAIN_STAGE_TYPES = frozenset(
    [
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    ]
)


def parse_review_plan_arguments(
    state: dict,
) -> tuple[StageType, int, StageType | None] | None:
    """Return main stage type, main stage size and preliminary type, or
    `None` if the state is incomplete or invalid."""
    try:
        main_stage_type = StageType(state['main_stage_type'])
        main_stage_size = int(state['main_stage_size'])
    except KeyError, TypeError, ValueError:
        return None

    preliminary_type_result = _parse_preliminary_type(state)
    if preliminary_type_result.is_err():
        return None

    return main_stage_type, main_stage_size, preliminary_type_result.unwrap()


def _parse_preliminary_type(state: dict) -> Result[StageType | None, None]:
    if not state.get('use_preliminary'):
        return Ok(None)

    raw_preliminary_type = state.get('preliminary_type')
    if not raw_preliminary_type:
        return Err(None)
    try:
        return Ok(StageType(raw_preliminary_type))
    except ValueError:
        return Err(None)


def build_review_preview_lines(
    preview: dict,
    main_stage_type: StageType,
    main_stage_size: int,
    preliminary_type: StageType | None,
) -> list[str]:
    lines = [
        gettext(
            'Aktuelle Generierungsbasis: %(count)s bereite Teilnehmer',
            count=preview['participant_count'],
        )
    ]

    if main_stage_type in FFA_MAIN_STAGE_TYPES:
        lines.extend(
            _build_ffa_lines(preview, main_stage_type, main_stage_size)
        )
    else:
        lines.extend(
            _build_duel_lines(preview, main_stage_size, preliminary_type)
        )

    return lines


# duel main stage


def _build_duel_lines(
    preview: dict, main_stage_size: int, preliminary_type: StageType | None
) -> list[str]:
    if preview['participant_count'] < 2:
        return [
            gettext(
                'Noch keine 2 bereiten Teilnehmer: Matches lassen sich erst ab 2 erzeugen.'
            )
        ]
    if preview['participant_count'] <= main_stage_size:
        return [
            gettext(
                'Mit der aktuellen Anzahl bereiter Teilnehmer ist keine Vorrunde nötig. Das Hauptturnier wird direkt erzeugt, eine angelegte Vorrunde übersprungen.'
            )
        ]
    if preliminary_type is None:
        return [
            gettext(
                'Mit der aktuellen Anzahl bereiter Teilnehmer wäre eine Vorrunde nötig. Ohne Vorrunde würde die spätere Generierung des Hauptturniers blockieren.'
            )
        ]
    if preliminary_type == StageType.round_robin_groups:
        return _build_round_robin_lines(preview, main_stage_size)
    if preliminary_type == StageType.swiss:
        return [_get_swiss_line(preview, main_stage_size)]
    return []


def _build_round_robin_lines(preview: dict, main_stage_size: int) -> list[str]:
    lines = [
        get_round_robin_strategy_line(preview.get('round_robin_builder_mode')),
        gettext('Gruppen: %(count)s', count=preview.get('group_count')),
    ]
    group_sizes = preview.get('group_sizes', [])
    if group_sizes:
        lines.extend(build_group_size_summary_lines(group_sizes))
    qualifiers_per_group = preview.get('qualifiers_per_group')
    if qualifiers_per_group:
        lines.append(
            get_group_qualification_line(qualifiers_per_group, main_stage_size)
        )
    lines.append(get_group_materialization_line())
    if preview.get('match_count') is not None:
        lines.append(
            gettext(
                '%(count)s Vorrunden-Matches insgesamt',
                count=preview['match_count'],
            )
        )
    return lines


def _get_swiss_line(preview: dict, main_stage_size: int) -> str:
    return gettext(
        'Swiss-Vorrunde: Schwelle %(threshold)s/%(threshold)s, %(round_count)s Runden, Qualifikation Top %(size)s insgesamt',
        threshold=preview.get('swiss_threshold'),
        round_count=preview.get('round_count'),
        size=main_stage_size,
    )
