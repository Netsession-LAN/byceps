"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_form_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for the stage create and update routes in `routes_stage_form`:
default forms, source stages, settings from the form, saving.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_participant_source import (
    participant_source_settings_from_form,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_form_data import (
    stage_to_form_data,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_meta import (
    build_stage_builder_generation_summary,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_settings import (
    stage_settings_from_form,
)
from byceps.services.netsession_tourney.forms import StageForm
from byceps.services.netsession_tourney.models import StageType
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.netsession_tourney.stage_service import (
    create_stage,
    update_stage,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_success
from byceps.util.result import Err, Ok, Result


_PARTICIPANT_SOURCE_SETTING_KEYS = (
    'participant_source_mode',
    'qualifier_source_stage_ids',
    'qualifier_top_n',
)


def build_default_stage_create_form(tournament: Any) -> StageForm:
    return StageForm(
        data={'result_report_mode': 'both_must_confirm'},
        tournament_mode=tournament.mode,
        registration_mode=tournament.registration_mode.value,
    )


def build_default_stage_update_form(tournament: Any, stage: Any) -> StageForm:
    return StageForm(
        data=stage_to_form_data(stage),
        tournament_mode=tournament.mode,
        registration_mode=tournament.registration_mode.value,
    )


def build_posted_stage_form(tournament: Any) -> StageForm:
    return StageForm(
        request.form,
        tournament_mode=tournament.mode,
        registration_mode=tournament.registration_mode.value,
    )


def stage_type_or_none(value: Any) -> StageType | None:
    return (
        StageType(value)
        if value in {stage_type.value for stage_type in StageType}
        else None
    )


def earlier_source_stages(stages: list, stage: Any) -> list:
    """Return the stages before `stage`, the possible sources of its
    participants."""
    return [
        stage_item
        for stage_item in stages
        if stage_item.id != stage.id and stage_item.order_no < stage.order_no
    ]


def build_update_generation_summary(
    party: Party, tournament: Any, stage: Any, stage_builder_meta: Any
) -> Any:
    if stage_builder_meta is None:
        return None

    preview_result = preview_stage_match_generation(
        party.id, tournament.id, stage.id
    )
    if not preview_result.is_ok():
        return None

    preview = preview_result.unwrap()
    return build_stage_builder_generation_summary(
        stage,
        preview.stage,
        preview.participant_count,
        match_count=preview.match_count,
    )


def create_stage_from_form(
    party: Party, tournament: Any, form: StageForm
) -> Result[None, str]:
    stages = get_stages_for_tournament(party.id, tournament.id)
    eligible_source_stages = {
        stage_item.id: stage_item for stage_item in stages
    }
    participant_source_result = participant_source_settings_from_form(
        request.form, eligible_source_stages=eligible_source_stages
    )
    if participant_source_result.is_err():
        return Err(participant_source_result.unwrap_err())

    stage_settings_result = stage_settings_from_form(form)
    if stage_settings_result.is_err():
        return Err(stage_settings_result.unwrap_err())

    settings = stage_settings_result.unwrap()
    settings.update(participant_source_result.unwrap())

    stage_type = StageType(form.type.data)
    return _flash_saved(
        create_stage(
            party.id,
            tournament.id,
            stage_type,
            form.name.data,
            settings,
            g.user.as_user(),
        ),
        gettext('Phase wurde angelegt.'),
    )


def update_stage_from_form(
    party: Party, tournament: Any, stage: Any, stage_id: Any, form: StageForm
) -> Result[None, str]:
    stages = get_stages_for_tournament(party.id, tournament.id)
    eligible_source_stages = {
        stage_item.id: stage_item
        for stage_item in earlier_source_stages(stages, stage)
    }
    participant_source_result = participant_source_settings_from_form(
        request.form, eligible_source_stages=eligible_source_stages
    )
    if participant_source_result.is_err():
        return Err(participant_source_result.unwrap_err())

    stage_settings_result = stage_settings_from_form(
        form, existing_settings=stage.settings
    )
    if stage_settings_result.is_err():
        return Err(stage_settings_result.unwrap_err())

    settings = stage_settings_result.unwrap()
    for key in _PARTICIPANT_SOURCE_SETTING_KEYS:
        settings.pop(key, None)
    settings.update(participant_source_result.unwrap())

    stage_type = StageType(form.type.data)
    return _flash_saved(
        update_stage(
            party.id,
            tournament.id,
            stage_id,
            stage_type,
            form.name.data,
            settings,
            g.user.as_user(),
        ),
        gettext('Phase wurde gespeichert.'),
    )


def _flash_saved(result: Result[Any, str], message: str) -> Result[None, str]:
    if result.is_err():
        return Err(result.unwrap_err())

    flash_success(message)
    return Ok(None)
