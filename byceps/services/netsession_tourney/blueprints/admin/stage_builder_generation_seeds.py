"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_generation_seeds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Seeds on the stage generation form: parsing the submitted
automatic and manual seeds, and the rows shown to the admin.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask_babel import gettext

from byceps.services.netsession_tourney.models import (
    ParticipantID,
)
from byceps.util.result import Err, Ok, Result


def parse_stage_generation_auto_seed_participant_ids(
    request_form, allowed_participant_ids: set[ParticipantID]
) -> Result[list[ParticipantID], str]:
    auto_seed_participant_ids: list[ParticipantID] = []
    seen_participant_ids: set[ParticipantID] = set()

    for raw_participant_id in request_form.getlist('auto_seed_participant_ids'):
        try:
            participant_id = ParticipantID(UUID(raw_participant_id))
        except ValueError:
            return Err(
                gettext('Ungültige Zuordnung der automatischen Setzplätze.')
            )
        if participant_id not in allowed_participant_ids:
            return Err(gettext('Die Teilnehmerliste hat sich geändert.'))
        if participant_id in seen_participant_ids:
            return Err(
                gettext('Die Liste der automatischen Setzplätze ist ungültig.')
            )
        seen_participant_ids.add(participant_id)
        auto_seed_participant_ids.append(participant_id)

    if seen_participant_ids != allowed_participant_ids:
        return Err(
            gettext(
                'Die Teilnehmerliste hat sich geändert. Bitte die Setzlisten-Seite neu laden.'
            )
        )

    return Ok(auto_seed_participant_ids)


def parse_stage_generation_manual_seed_values_by_participant_id(
    request_form, allowed_participant_ids: set[ParticipantID]
) -> Result[dict[ParticipantID, int], str]:
    manual_seed_values_by_participant_id: dict[ParticipantID, int] = {}

    for raw_key, raw_value in request_form.items():
        if not raw_key.startswith('manual_seed_'):
            continue

        participant_id_result = _parse_manual_seed_participant_id(
            raw_key, allowed_participant_ids
        )
        if participant_id_result.is_err():
            return Err(participant_id_result.unwrap_err())

        seed_result = _parse_manual_seed_value(raw_value)
        if seed_result.is_err():
            return Err(seed_result.unwrap_err())

        seed = seed_result.unwrap()
        if seed is None:
            continue

        manual_seed_values_by_participant_id[participant_id_result.unwrap()] = (
            seed
        )

    return Ok(manual_seed_values_by_participant_id)


def _parse_manual_seed_participant_id(
    raw_key: str, allowed_participant_ids: set[ParticipantID]
) -> Result[ParticipantID, str]:
    try:
        participant_id = ParticipantID(
            UUID(raw_key.removeprefix('manual_seed_'))
        )
    except ValueError:
        return Err(gettext('Ungültige Eingabe des Setzplatzes.'))

    if participant_id not in allowed_participant_ids:
        return Err(gettext('Die Teilnehmerliste hat sich geändert.'))

    return Ok(participant_id)


def _parse_manual_seed_value(raw_value: str | None) -> Result[int | None, str]:
    normalized_raw_value = (raw_value or '').strip()
    if not normalized_raw_value:
        return Ok(None)

    try:
        seed = int(normalized_raw_value)
    except ValueError:
        return Err(gettext('Manuelle Setzplätze müssen Zahlen sein.'))

    if seed < 1:
        return Err(gettext('Manuelle Setzplätze müssen bei 1 beginnen.'))

    return Ok(seed)


def build_stage_generation_seed_rows(
    participants,
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_values_by_participant_id: dict[ParticipantID, int],
):
    participants_by_id = {
        participant.id: participant for participant in participants
    }
    auto_seed_by_participant_id = {
        participant_id: index
        for index, participant_id in enumerate(
            auto_seed_participant_ids, start=1
        )
    }
    final_seed_by_participant_id = _build_final_seed_by_participant_id(
        auto_seed_participant_ids, manual_seed_values_by_participant_id
    )

    rows = []
    for participant_id in auto_seed_participant_ids:
        manual_seed = manual_seed_values_by_participant_id.get(participant_id)
        rows.append(
            {
                'participant': participants_by_id[participant_id],
                'auto_seed': auto_seed_by_participant_id[participant_id],
                'manual_seed': manual_seed,
                'final_seed': final_seed_by_participant_id[participant_id],
                'is_manual': manual_seed is not None,
            }
        )

    return rows


def _build_final_seed_by_participant_id(
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_values_by_participant_id: dict[ParticipantID, int],
) -> dict[ParticipantID, int]:
    manual_prefix_participant_ids = [
        participant_id
        for participant_id, _seed in sorted(
            manual_seed_values_by_participant_id.items(),
            key=lambda item: item[1],
        )
    ]
    remaining_participant_ids = [
        participant_id
        for participant_id in auto_seed_participant_ids
        if participant_id not in manual_seed_values_by_participant_id
    ]
    return {
        participant_id: index
        for index, participant_id in enumerate(
            manual_prefix_participant_ids + remaining_participant_ids, start=1
        )
    }
