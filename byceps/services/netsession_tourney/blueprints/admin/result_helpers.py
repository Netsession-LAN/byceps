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

from byceps.services.netsession_tourney.blueprints.admin.result_form_ffa import (
    build_ffa_score_and_ranking,
    get_ffa_winner_slot,
    parse_ffa_slot_entries,
)
from byceps.services.netsession_tourney.blueprints.admin.result_form_helpers import (
    build_flatout2_score_and_ranking,
    get_flatout2_winner_slot,
    get_occupied_slots,
    parse_flatout2_slot_points,
    parse_result_comment,
)
from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from byceps.services.netsession_tourney.tournament_service import (
    find_tournament_for_party,
)
from byceps.services.party import party_service
from byceps.services.party.models import Party
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7
from byceps.util.views import redirect_to


def get_party_or_404(party_id) -> Party:
    party = party_service.find_party(party_id)
    if party is None:
        abort(404)
    return party


def _get_tournament_or_404(party_id, tournament_id):
    tournament = find_tournament_for_party(party_id, tournament_id)
    if tournament is None:
        abort(404)
    return tournament


def get_stage_or_404(party_id, tournament_id, stage_id):
    stages = get_stages_for_tournament(party_id, tournament_id)
    for stage in stages:
        if stage.id == stage_id:
            return stage

    abort(404)


def get_participant_or_404(party_id, tournament_id, participant_id):
    """Admins also see dropped participants."""
    participants = get_participants_for_tournament(
        party_id, tournament_id, include_dropped=True
    )
    for participant in participants:
        if participant.id == participant_id:
            return participant

    abort(404)


def get_dropped_participants(party_id, tournament_id):
    return [
        participant
        for participant in get_participants_for_tournament(
            party_id, tournament_id, include_dropped=True
        )
        if participant.status.value == 'dropped'
    ]


def get_round_neighbours(party_id, tournament_id, match):
    """The previous and next match of the same phase and round (or None)."""
    same_round = _get_same_round_matches(party_id, tournament_id, match)
    ids = [item.id for item in same_round]
    index = ids.index(match.id) if match.id in ids else -1
    if index < 0:
        return None, None
    return _get_neighbours_at(same_round, index)


def _get_same_round_matches(party_id, tournament_id, match) -> list:
    return sorted(
        (
            item
            for item in get_matches_for_tournament(party_id, tournament_id)
            if item.stage_id == match.stage_id
            and item.round_no == match.round_no
        ),
        key=lambda item: item.match_no,
    )


def _get_neighbours_at(same_round: list, index: int) -> tuple:
    previous = same_round[index - 1] if index > 0 else None
    following = same_round[index + 1] if index + 1 < len(same_round) else None
    return previous, following


def get_match_or_404(party_id, tournament_id, match_id):
    matches = get_matches_for_tournament(party_id, tournament_id)
    for match in matches:
        if match.id == match_id:
            return match

    abort(404)


def redirect_to_related_tournament_view(party_id: str, tournament_id: UUID):
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


def redirect_to_participant_or_tournament_view(
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

    return redirect_to_related_tournament_view(party_id, tournament_id)


def redirect_to_match_or_tournament_view(
    party_id: str, tournament_id: UUID, match_id: UUID
):
    return_to_match = (
        request.form.get('return_to') == 'match'
        or request.args.get('return_to') == 'match'
    )
    if return_to_match:
        redirect_kwargs = _build_match_redirect_kwargs(
            party_id, tournament_id, match_id
        )
        return redirect_to(
            '.match_view',
            **redirect_kwargs,
        )

    return redirect_to_related_tournament_view(party_id, tournament_id)


def _build_match_redirect_kwargs(
    party_id: str, tournament_id: UUID, match_id: UUID
) -> dict:
    redirect_kwargs = {
        'party_id': party_id,
        'tournament_id': tournament_id,
        'match_id': match_id,
    }
    parent_return_to = (
        _get_form_or_query_value('parent_return_to').strip().lower()
    )
    if parent_return_to in {'stages', 'matches'}:
        redirect_kwargs['return_to'] = parent_return_to

    if parent_return_to == 'stages':
        parent_stage_id = _get_parent_stage_id()
        if parent_stage_id is not None:
            redirect_kwargs['stage_id'] = parent_stage_id

    return redirect_kwargs


def _get_form_or_query_value(name: str) -> str:
    return request.form.get(name) or request.args.get(name) or ''


def _get_parent_stage_id() -> UUID | None:
    raw_parent_stage_id = _get_form_or_query_value('parent_stage_id').strip()
    if not raw_parent_stage_id:
        return None

    try:
        return UUID(raw_parent_stage_id)
    except ValueError:
        return None


def build_score_payload(raw_score: str | None) -> dict:
    if raw_score is None:
        return {}

    score = raw_score.strip()
    if not score:
        return {}

    return {'display': score}


def parse_admin_ffa_result_form(
    request_form,
    slots,
    *,
    placement_points_rules,
) -> Result[tuple[int, dict, dict, str | None], str]:
    occupied_slots = get_occupied_slots(slots)
    if len(occupied_slots) < 2:
        return Err(
            gettext(
                'Ein FFA-Match braucht mindestens zwei belegte Slots, bevor ein Ergebnis gespeichert werden kann.'
            )
        )

    entries_result = parse_ffa_slot_entries(request_form, occupied_slots)
    if entries_result.is_err():
        return Err(entries_result.unwrap_err())

    placements_by_slot_no, kills_by_slot_no = entries_result.unwrap()

    winner_slot_result = get_ffa_winner_slot(placements_by_slot_no)
    if winner_slot_result.is_err():
        return Err(winner_slot_result.unwrap_err())

    winner_slot = winner_slot_result.unwrap()
    score, ranking = build_ffa_score_and_ranking(
        placements_by_slot_no, kills_by_slot_no, placement_points_rules
    )
    comment = parse_result_comment(request_form)

    return Ok((winner_slot, score, ranking, comment))


def parse_admin_flatout2_result_form(
    request_form,
    slots,
) -> Result[tuple[int, dict, dict, str | None], str]:
    occupied_slots = get_occupied_slots(slots)
    if len(occupied_slots) < 2:
        return Err(
            gettext(
                'Ein FlatOut-2-Match braucht mindestens zwei belegte Slots, bevor ein Ergebnis gespeichert werden kann.'
            )
        )

    points_result = parse_flatout2_slot_points(request_form, occupied_slots)
    if points_result.is_err():
        return Err(points_result.unwrap_err())

    points_by_slot_no = points_result.unwrap()

    winner_slot_result = get_flatout2_winner_slot(points_by_slot_no)
    if winner_slot_result.is_err():
        return Err(winner_slot_result.unwrap_err())

    winner_slot = winner_slot_result.unwrap()
    score, ranking = build_flatout2_score_and_ranking(points_by_slot_no)
    comment = parse_result_comment(request_form)

    return Ok((winner_slot, score, ranking, comment))


def get_or_create_idempotency_key(raw_key: str | None) -> str:
    if raw_key:
        key = raw_key.strip()
        if key:
            return key

    return f'admin-{generate_uuid7()}'


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(',') if part.strip()]
