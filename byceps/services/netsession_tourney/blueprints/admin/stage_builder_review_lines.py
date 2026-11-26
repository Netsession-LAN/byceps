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


# FFA main stage


def _build_ffa_lines(
    preview: dict, main_stage_type: StageType, main_stage_size: int
) -> list[str]:
    lines = _build_ffa_participant_lines(preview, main_stage_size)
    lines.append(
        gettext(
            'Heat-Größe: bis zu %(count)s Teilnehmer pro Match.',
            count=preview.get('max_players_per_match') or '-',
        )
    )
    lines.append(_get_ffa_qualification_line(main_stage_type))

    if preview.get('expected_final_heat_size'):
        lines.append(
            gettext(
                'Erwartete Finalgröße: bis zu %(count)s Teilnehmer im letzten Heat.',
                count=preview.get('expected_final_heat_size'),
            )
        )

    lines.extend(
        _build_preliminary_round_summary_lines(
            preview.get('preliminary_round_summaries', [])
        )
    )
    lines.extend(
        _build_main_round_summary_lines(
            preview.get('main_round_summaries')
            or preview.get('round_summaries', [])
        )
    )
    lines.extend(_build_ffa_match_count_lines(preview))
    return lines


def _build_ffa_participant_lines(
    preview: dict, main_stage_size: int
) -> list[str]:
    if preview.get('generation_blocked_without_preliminary'):
        return _build_ffa_blocked_lines(preview, main_stage_size)
    if preview.get('uses_preliminary'):
        return _build_ffa_preliminary_lines(preview, main_stage_size)
    return _build_ffa_direct_lines(preview)


def _build_ffa_blocked_lines(preview: dict, main_stage_size: int) -> list[str]:
    return [
        gettext(
            'Mit der aktuellen Zahl bereiter Teilnehmer würde das Hauptturnier noch blockieren: %(participant_count)s Teilnehmer überschreiten die Zielgröße %(target_size)s.',
            participant_count=preview.get('participant_count') or 0,
            target_size=main_stage_size,
        ),
        gettext(
            'Aktiviere eine Vorrunde oder erhöhe die Zielgröße des Hauptturniers.'
        ),
    ]


def _build_ffa_preliminary_lines(
    preview: dict, main_stage_size: int
) -> list[str]:
    return [
        gettext(
            'Vorrunde aktiv: %(participant_count)s bereite Teilnehmer starten zuerst in %(preliminary_type)s.',
            participant_count=preview.get('participant_count') or 0,
            preliminary_type=(
                'FlatOut 2'
                if preview.get('preliminary_type')
                == StageType.ffa_flatout2_single_elimination
                else 'FFA Single Elimination'
            ),
        ),
        gettext(
            'Danach ziehen exakt %(count)s Teilnehmer in das Hauptturnier ein.',
            count=preview.get('main_stage_participant_count')
            or main_stage_size,
        ),
    ]


def _build_ffa_direct_lines(preview: dict) -> list[str]:
    return [
        gettext(
            'Das Hauptturnier startet direkt mit %(count)s bereiten Teilnehmern.',
            count=preview.get('main_stage_participant_count')
            or preview.get('participant_count')
            or 0,
        )
    ]


def _get_ffa_qualification_line(main_stage_type: StageType) -> str:
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        return gettext(
            'FlatOut 2: Top 3 je Heat qualifizieren sich jeweils für die nächste Runde.'
        )

    return gettext(
        'FFA Single Elimination: Die Qualifikanten je Heat werden automatisch aus der Heat-Verteilung der Folgerunde abgeleitet.'
    )


def _build_preliminary_round_summary_lines(round_summaries) -> list[str]:
    if not round_summaries:
        return []

    return [gettext('Vorrunden-Preview:')] + [
        gettext(
            'Vorrunde %(round_no)s: %(match_count)s Heats mit bis zu %(max_heat_size)s Teilnehmern',
            round_no=round_summary.get('round_no'),
            match_count=round_summary.get('match_count'),
            max_heat_size=round_summary.get('max_heat_size'),
        )
        for round_summary in round_summaries
    ]


def _build_main_round_summary_lines(round_summaries) -> list[str]:
    if not round_summaries:
        return []

    return [gettext('Vorschau Hauptturnier:')] + [
        gettext(
            'Hauptturnier Runde %(round_no)s: %(match_count)s Heats mit bis zu %(max_heat_size)s Teilnehmern',
            round_no=round_summary.get('round_no'),
            match_count=round_summary.get('match_count'),
            max_heat_size=round_summary.get('max_heat_size'),
        )
        for round_summary in round_summaries
    ]


def _build_ffa_match_count_lines(preview: dict) -> list[str]:
    lines = []
    if preview.get('preliminary_match_count') is not None:
        lines.append(
            gettext(
                '%(count)s Vorrunden-Matches im aktuellen Preview',
                count=preview.get('preliminary_match_count'),
            )
        )
    if preview.get('main_match_count') is not None:
        lines.append(
            gettext(
                '%(count)s Matches im Hauptturnier im aktuellen Preview',
                count=preview.get('main_match_count'),
            )
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
