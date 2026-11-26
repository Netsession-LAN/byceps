"""
byceps.services.netsession_tourney.blueprints.site.stage_render_ffa_match_details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participant rows and per slot values (placement, kills, points) of
FFA matches.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .presentation_helpers import (
    get_participant_image,
)


def _build_ffa_match_participant_data(
    slot,
    participants_by_id,
    users_by_id,
    winner_slot: int | None,
    kills: str | None,
    placement: int | None,
    points: int | None = None,
    *,
    is_host: bool = False,
) -> dict:
    participant = participants_by_id.get(slot.participant_id)
    image_url, image_alt = get_participant_image(participant, users_by_id)

    return {
        'slot_no': slot.slot_no,
        'name': participant.name
        if participant is not None
        else gettext('offen'),
        'participant': participant,
        'image_url': image_url,
        'image_alt': image_alt,
        'kills': kills or '-',
        'kills_value': parse_score_int(kills),
        'placement': placement,
        'points': points if points is not None else 0,
        'is_winner': winner_slot is not None and slot.slot_no == winner_slot,
        'is_host': is_host,
    }


def build_ffa_match_detail_rows(
    slots,
    participants_by_id,
    users_by_id,
    result,
    slot_scores,
    *,
    is_flatout2_match: bool = False,
):
    placement_by_slot_no = _get_ffa_placement_by_slot_no(result, slots)
    points_by_slot_no = get_ffa_points_by_slot_no(result, slots)
    rows = [
        _build_ffa_match_participant_data(
            slot,
            participants_by_id,
            users_by_id,
            result.winner_slot if result else None,
            slot_scores.get(slot.slot_no),
            placement_by_slot_no.get(slot.slot_no),
            points_by_slot_no.get(slot.slot_no),
        )
        for slot in slots
        if slot.participant_id is not None
    ]
    rows.sort(
        key=_get_points_sort_key if is_flatout2_match else _get_kills_sort_key
    )
    return rows


def _get_placement_sort_value(row) -> int:
    return row['placement'] if row['placement'] is not None else 999999


def _get_kills_sort_key(row) -> tuple:
    return (
        _get_placement_sort_value(row),
        -row['kills_value'],
        row['slot_no'],
        row['name'].lower(),
    )


def _get_points_sort_key(row) -> tuple:
    return (
        _get_placement_sort_value(row),
        -row['points'],
        row['slot_no'],
        row['name'].lower(),
    )


def _get_ffa_placement_by_slot_no(result, slots) -> dict[int, int]:
    return _get_ffa_ranking_ints_by_slot_no(result, slots, 'placements')


def get_ffa_points_by_slot_no(result, slots) -> dict[int, int]:
    return _get_ffa_ranking_ints_by_slot_no(result, slots, 'points')


def _get_ffa_ranking_ints_by_slot_no(
    result, slots, ranking_key: str
) -> dict[int, int]:
    if result is None or not isinstance(result.ranking, dict):
        return {}

    raw_values = result.ranking.get(ranking_key)
    if not isinstance(raw_values, dict):
        return {}

    values = {}
    for slot in slots:
        raw_value = get_slot_keyed_value(raw_values, slot.slot_no)
        try:
            values[slot.slot_no] = int(raw_value)
        except TypeError, ValueError:
            continue

    return values


def get_slot_keyed_value(raw_values: dict, slot_no: int):
    """Return the value stored under the slot number as string key,
    falling back to the slot number as integer key.
    """
    raw_value = raw_values.get(str(slot_no))
    if raw_value is None:
        raw_value = raw_values.get(slot_no)
    return raw_value


def parse_score_int(value: str | None) -> int:
    try:
        return int(value or '0')
    except TypeError, ValueError:
        return 0
