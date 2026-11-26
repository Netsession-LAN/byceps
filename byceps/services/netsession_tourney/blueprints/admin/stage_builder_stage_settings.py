"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage settings from the submitted stage form.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_placement_points import (
    parse_ffa_placement_points_text,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_form_data import (
    _is_ffa_scoring_stage_type,
    is_ffa_result_stage_type,
)
from byceps.services.netsession_tourney.forms import (
    StageForm,
)
from byceps.services.netsession_tourney.models import (
    StageType,
)
from byceps.services.netsession_tourney.result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from byceps.services.netsession_tourney.swiss_thresholds import (
    get_swiss_round_count_for_threshold,
)
from byceps.util.result import Err, Ok, Result


def stage_settings_from_form(
    form: StageForm, *, existing_settings: dict | None = None
) -> Result[dict, str]:
    stage_type = _parse_stage_type(form.type.data)

    settings = {}
    if stage_type == StageType.swiss and form.swiss_threshold.data is None:
        return Err(gettext('Bitte eine Swiss-Schwelle auswählen.'))

    _add_round_settings(settings, form, stage_type)
    _add_match_size_settings(settings, form, stage_type)
    if _is_ffa_scoring_stage_type(stage_type):
        parsed_rules_result = parse_ffa_placement_points_text(
            form.placement_points.data
        )
        if parsed_rules_result.is_err():
            return Err(parsed_rules_result.unwrap_err())

        _add_ffa_scoring_settings(settings, form, parsed_rules_result.unwrap())
    _add_timing_settings(settings, form, stage_type)
    settings['result_report_mode'] = _get_result_report_mode(form, stage_type)

    if existing_settings is not None:
        _copy_participant_source_settings(settings, existing_settings)

    return Ok(settings)


def _parse_stage_type(raw_stage_type) -> StageType | None:
    try:
        return StageType(raw_stage_type)
    except ValueError:
        return None


def _add_round_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.round_count.data and stage_type != StageType.swiss:
        settings['round_count'] = form.round_count.data
    if stage_type == StageType.swiss and form.swiss_threshold.data:
        settings['swiss_threshold'] = form.swiss_threshold.data
        settings['round_count'] = get_swiss_round_count_for_threshold(
            form.swiss_threshold.data
        )


def _add_match_size_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.max_players_per_match.data and stage_type != StageType.ffa_simple:
        settings['max_players_per_match'] = form.max_players_per_match.data
    if form.group_size.data:
        settings['group_size'] = form.group_size.data


def _add_ffa_scoring_settings(
    settings: dict, form: StageForm, placement_points_rules: list[dict]
) -> None:
    settings['placement_points_rules'] = placement_points_rules
    settings['points_per_kill'] = (
        form.points_per_kill.data
        if form.points_per_kill.data is not None
        else 1
    )


def _add_timing_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.match_duration_minutes.data:
        settings['match_duration_minutes'] = form.match_duration_minutes.data
    if form.max_matches_per_round.data and stage_type not in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        settings['max_matches_per_round'] = form.max_matches_per_round.data
    if form.break_between_rounds_minutes.data is not None:
        settings['break_between_rounds_minutes'] = (
            form.break_between_rounds_minutes.data
        )


def _get_result_report_mode(
    form: StageForm, stage_type: StageType | None
) -> str:
    return (
        RESULT_REPORT_MODE_ADMIN_ONLY
        if is_ffa_result_stage_type(stage_type)
        else (form.result_report_mode.data or 'both_must_confirm')
    )


def _copy_participant_source_settings(
    settings: dict, existing_settings: dict
) -> None:
    for key in (
        'participant_source_mode',
        'qualifier_source_stage_ids',
        'qualifier_top_n',
    ):
        if key in existing_settings:
            settings[key] = existing_settings[key]
