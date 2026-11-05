"""
byceps.services.netsession_tourney.blueprints.admin.result_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import abort, request
from flask_babel import gettext

from byceps.services.party import party_service
from byceps.services.party.models import Party
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7
from byceps.util.views import redirect_to

from ...match_queries import get_matches_for_tournament
from ...tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from ...tournament_service import find_tournament_for_party


def _get_party_or_404(party_id) -> Party:
    party = party_service.find_party(party_id)
    if party is None:
        abort(404)
    return party


def _get_tournament_or_404(party_id, tournament_id):
    tournament = find_tournament_for_party(party_id, tournament_id)
    if tournament is None:
        abort(404)
    return tournament


def _get_stage_or_404(party_id, tournament_id, stage_id):
    stages = get_stages_for_tournament(party_id, tournament_id)
    for stage in stages:
        if stage.id == stage_id:
            return stage

    abort(404)


def _get_participant_or_404(party_id, tournament_id, participant_id):
    participants = get_participants_for_tournament(party_id, tournament_id)
    for participant in participants:
        if participant.id == participant_id:
            return participant

    abort(404)


def _get_match_or_404(party_id, tournament_id, match_id):
    matches = get_matches_for_tournament(party_id, tournament_id)
    for match in matches:
        if match.id == match_id:
            return match

    abort(404)


def _redirect_to_related_tournament_view(
    party_id: str, tournament_id: UUID
):
    path = request.path
    tab = 'overview'
    if '/stages' in path:
        tab = 'stages'
    elif '/participants/' in path or '/teams/' in path:
        tab = 'participants'
    elif '/matches/' in path:
        tab = 'matches'
    elif '/discord' in path:
        tab = 'discord'

    return redirect_to(
        '.view',
        party_id=party_id,
        tournament_id=tournament_id,
        tab=tab,
    )


def _redirect_to_participant_or_tournament_view(
    party_id: str, tournament_id: UUID, participant_id: UUID
):
    return_to_participant = (
        request.form.get('return_to') == 'participant'
        or request.args.get('return_to') == 'participant'
    )
    if return_to_participant:
        return redirect_to(
            '.participant_view',
            party_id=party_id,
            tournament_id=tournament_id,
            participant_id=participant_id,
        )

    return _redirect_to_related_tournament_view(party_id, tournament_id)


def _redirect_to_match_or_tournament_view(
    party_id: str, tournament_id: UUID, match_id: UUID
):
    return_to_match = (
        request.form.get('return_to') == 'match'
        or request.args.get('return_to') == 'match'
    )
    if return_to_match:
        redirect_kwargs = {
            'party_id': party_id,
            'tournament_id': tournament_id,
            'match_id': match_id,
        }
        parent_return_to = (
            request.form.get('parent_return_to')
            or request.args.get('parent_return_to')
            or ''
        ).strip().lower()
        if parent_return_to in {'stages', 'matches'}:
            redirect_kwargs['return_to'] = parent_return_to

        if parent_return_to == 'stages':
            raw_parent_stage_id = (
                request.form.get('parent_stage_id')
                or request.args.get('parent_stage_id')
                or ''
            ).strip()
            if raw_parent_stage_id:
                try:
                    redirect_kwargs['stage_id'] = UUID(raw_parent_stage_id)
                except ValueError:
                    pass

        return redirect_to(
            '.match_view',
            **redirect_kwargs,
        )

    return _redirect_to_related_tournament_view(party_id, tournament_id)


def _build_score_payload(raw_score: str | None) -> dict:
    if raw_score is None:
        return {}

    score = raw_score.strip()
    if not score:
        return {}

    return {'display': score}


def _parse_admin_ffa_result_form(
    request_form,
    slots,
    *,
    placement_points_rules,
) -> Result[tuple[int, dict, dict, str | None], str]:
    occupied_slots = [slot for slot in slots if slot.participant_id is not None]
    if len(occupied_slots) < 2:
        return Err(
            gettext(
                'Ein FFA-Match braucht mindestens zwei belegte Slots, bevor ein Ergebnis gespeichert werden kann.'
            )
        )

    placements_by_slot_no: dict[int, int] = {}
    kills_by_slot_no: dict[int, int] = {}
    for slot in occupied_slots:
        raw_placement = (
            request_form.get(f'placement_slot_{slot.slot_no}') or ''
        ).strip()
        if not raw_placement:
            return Err(
                gettext(
                    'Bitte für jeden belegten Slot einen Ingame-Platz eintragen.'
                )
            )
        try:
            placement = int(raw_placement)
        except ValueError:
            return Err(
                gettext(
                    'Ingame-Plätze müssen als ganze Zahl eingetragen werden.'
                )
            )
        if placement < 1 or placement > 999:
            return Err(
                gettext(
                    'Ingame-Plätze müssen zwischen 1 und 999 liegen.'
                )
            )

        raw_kills = (request_form.get(f'kills_slot_{slot.slot_no}') or '').strip()
        if not raw_kills:
            return Err(
                gettext(
                    'Bitte für jeden belegten Slot eine Kill-Zahl eintragen.'
                )
            )
        try:
            kills = int(raw_kills)
        except ValueError:
            return Err(
                gettext('Kills müssen als ganze Zahl eingetragen werden.')
            )
        if kills < 0 or kills > 999:
            return Err(gettext('Kills müssen zwischen 0 und 999 liegen.'))

        placements_by_slot_no[slot.slot_no] = placement
        kills_by_slot_no[slot.slot_no] = kills

    if len(set(placements_by_slot_no.values())) != len(placements_by_slot_no):
        return Err(
            gettext(
                'Jeder belegte Slot braucht einen eindeutigen Ingame-Platz.'
            )
        )

    winner_slots = [
        slot_no
        for slot_no, placement in placements_by_slot_no.items()
        if placement == 1
    ]
    if len(winner_slots) != 1:
        return Err(
            gettext(
                'Genau ein belegter Slot muss den Ingame-Platz 1 erhalten.'
            )
        )

    winner_slot = winner_slots[0]
    points_by_slot_no = {
        slot_no: _get_ffa_points_for_placement(
            placement_points_rules, placement
        )
        for slot_no, placement in placements_by_slot_no.items()
    }

    score = {
        'display': gettext('Erfasst'),
        'slots': {
            str(slot_no): kills
            for slot_no, kills in sorted(kills_by_slot_no.items())
        },
        'metric': 'kills',
    }
    ranking = {
        'metric': 'placement_points',
        'placements': {
            str(slot_no): placement
            for slot_no, placement in sorted(placements_by_slot_no.items())
        },
        'points': {
            str(slot_no): points
            for slot_no, points in sorted(points_by_slot_no.items())
        },
    }
    comment = (request_form.get('comment') or '').strip() or None

    return Ok((winner_slot, score, ranking, comment))


def _parse_admin_flatout2_result_form(
    request_form,
    slots,
) -> Result[tuple[int, dict, dict, str | None], str]:
    occupied_slots = [slot for slot in slots if slot.participant_id is not None]
    if len(occupied_slots) < 2:
        return Err(
            gettext(
                'Ein FlatOut-2-Match braucht mindestens zwei belegte Slots, bevor ein Ergebnis gespeichert werden kann.'
            )
        )

    points_by_slot_no: dict[int, int] = {}
    for slot in occupied_slots:
        raw_points = (
            request_form.get(f'points_slot_{slot.slot_no}') or ''
        ).strip()
        if not raw_points:
            return Err(gettext('Bitte für jeden belegten Slot Punkte eintragen.'))
        try:
            points = int(raw_points)
        except ValueError:
            return Err(gettext('Punkte müssen als ganze Zahl eingetragen werden.'))
        if points < 0 or points > 9999:
            return Err(gettext('Punkte müssen zwischen 0 und 9999 liegen.'))

        points_by_slot_no[slot.slot_no] = points

    max_points = max(points_by_slot_no.values())
    winner_slots = [
        slot_no
        for slot_no, points in points_by_slot_no.items()
        if points == max_points
    ]
    if len(winner_slots) != 1:
        return Err(gettext('Der höchste Punktestand muss eindeutig sein.'))

    winner_slot = winner_slots[0]
    ordered_slot_nos = sorted(
        points_by_slot_no.keys(),
        key=lambda slot_no: (-points_by_slot_no[slot_no], slot_no),
    )
    placements_by_slot_no = {
        slot_no: index for index, slot_no in enumerate(ordered_slot_nos, start=1)
    }

    score = {
        'display': gettext('Erfasst'),
        'slots': {
            str(slot_no): points
            for slot_no, points in sorted(points_by_slot_no.items())
        },
        'metric': 'points',
    }
    ranking = {
        'metric': 'points',
        'placements': {
            str(slot_no): placement
            for slot_no, placement in sorted(placements_by_slot_no.items())
        },
        'points': {
            str(slot_no): points
            for slot_no, points in sorted(points_by_slot_no.items())
        },
    }
    comment = (request_form.get('comment') or '').strip() or None

    return Ok((winner_slot, score, ranking, comment))

def _get_ffa_points_for_placement(
    placement_points_rules, placement: int | None
) -> int:
    if placement is None or not isinstance(placement_points_rules, list):
        return 0

    for rule in placement_points_rules:
        if not isinstance(rule, dict):
            continue

        try:
            from_place = int(rule.get('from_place'))
            to_place = int(rule.get('to_place'))
            points = int(rule.get('points'))
        except (TypeError, ValueError):
            continue

        if from_place <= placement <= to_place:
            return points

    return 0


def _get_or_create_idempotency_key(raw_key: str | None) -> str:
    if raw_key:
        key = raw_key.strip()
        if key:
            return key

    return f'admin-{generate_uuid7()}'


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(',') if part.strip()]



