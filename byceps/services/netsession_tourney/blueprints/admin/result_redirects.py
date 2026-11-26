"""
byceps.services.netsession_tourney.blueprints.admin.result_redirects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Redirects back to the tournament, participant or match view
after an admin action.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import request

from byceps.util.views import redirect_to


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
