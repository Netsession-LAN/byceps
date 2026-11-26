"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_participant_source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participant source settings (qualifiers from earlier stages)
from the submitted stage form.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask_babel import gettext

from byceps.util.result import Err, Ok, Result


def participant_source_settings_from_form(
    request_form, *, eligible_source_stages
):
    mode = (request_form.get('participant_source_mode') or 'tournament').strip()
    if mode not in {'tournament', 'stage_qualifiers'}:
        return Err(gettext('Ungültige Teilnehmerquelle.'))

    settings = {'participant_source_mode': mode}

    if mode != 'stage_qualifiers':
        return Ok(settings)

    qualifier_settings_result = _parse_stage_qualifier_settings(
        request_form, eligible_source_stages
    )
    if qualifier_settings_result.is_err():
        return Err(qualifier_settings_result.unwrap_err())

    settings.update(qualifier_settings_result.unwrap())
    return Ok(settings)


def _parse_stage_qualifier_settings(
    request_form, eligible_source_stages
) -> Result[dict, str]:
    qualifier_selection_mode = (
        request_form.get('qualifier_selection_mode') or 'per_stage'
    ).strip()
    if qualifier_selection_mode not in {'per_stage', 'per_group'}:
        return Err(gettext('Ungültiger Qualifikationsmodus.'))

    selected_source_stage_ids = _parse_selected_source_stage_ids(
        request_form, eligible_source_stages
    )
    if not selected_source_stage_ids:
        return Err(
            gettext(
                'Bitte mindestens eine vorherige Phase als Quelle auswählen.'
            )
        )

    qualifier_top_n_result = _parse_qualifier_top_n(request_form)
    if qualifier_top_n_result.is_err():
        return Err(qualifier_top_n_result.unwrap_err())

    return Ok(
        {
            'qualifier_source_stage_ids': [
                str(selected_source_stage_id)
                for selected_source_stage_id in selected_source_stage_ids
            ],
            'qualifier_top_n': qualifier_top_n_result.unwrap(),
            'qualifier_selection_mode': qualifier_selection_mode,
        }
    )


def _parse_selected_source_stage_ids(
    request_form, eligible_source_stages
) -> list[UUID]:
    selected_source_stage_ids: list[UUID] = []
    for raw_stage_id in request_form.getlist('qualifier_source_stage_ids'):
        try:
            selected_source_stage_id = UUID(raw_stage_id)
        except ValueError:
            continue
        if selected_source_stage_id not in eligible_source_stages:
            continue
        if selected_source_stage_id not in selected_source_stage_ids:
            selected_source_stage_ids.append(selected_source_stage_id)
    return selected_source_stage_ids


def _parse_qualifier_top_n(request_form) -> Result[int, str]:
    raw_top_n = (request_form.get('qualifier_top_n') or '1').strip()
    try:
        qualifier_top_n = int(raw_top_n)
    except ValueError:
        qualifier_top_n = 0
    if qualifier_top_n < 1 or qualifier_top_n > 128:
        return Err(gettext('Top N muss zwischen 1 und 128 liegen.'))
    return Ok(qualifier_top_n)
