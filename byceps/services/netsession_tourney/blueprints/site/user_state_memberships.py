"""
byceps.services.netsession_tourney.blueprints.site.user_state_memberships
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Team, membership and seat data of the current user and of team
members.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, url_for
from flask_babel import gettext

from byceps.services.netsession_tourney.models import (
    ParticipantType,
    TeamMemberRole,
)
from byceps.services.netsession_tourney.team_captain_service import (
    find_managed_team_for_user,
)
from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_service

from .user_state_match_access import (
    can_user_report_match_result as can_user_report_match_result,
    format_open_match_participant_name as format_open_match_participant_name,
    is_match_involving_user as is_match_involving_user,
)


def get_captain_team_for_current_user(tournament_id):
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    return find_managed_team_for_user(g.party.id, tournament_id, user.id)


def _find_team_member_for_user(members, user_id):
    for member in members:
        if member.user_id == user_id:
            return member
    return None


def _find_participant_membership(participant, members_by_participant_id, user):
    if participant.type == ParticipantType.team:
        member = _find_team_member_for_user(
            members_by_participant_id.get(participant.id, []), user.id
        )
        if member is not None:
            return {
                'participant': participant,
                'member': member,
            }

    if participant.user_id == user.id:
        return {
            'participant': participant,
            'member': None,
        }

    return None


def get_current_user_tournament_membership(
    participants, members_by_participant_id
):
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    for participant in participants:
        membership = _find_participant_membership(
            participant, members_by_participant_id, user
        )
        if membership is not None:
            return membership

    return None


def format_team_member_role_label(role: TeamMemberRole) -> str:
    if role == TeamMemberRole.captain:
        return gettext('Teamkapitän')
    if role == TeamMemberRole.substitute:
        return gettext('Ersatzspieler')

    return gettext('Mitspieler')


def get_seat_data_by_user_id(party_id: PartyID, user_ids: set) -> dict:
    seat_data_by_user_id = {}

    for user_id in user_ids:
        tickets = ticket_service.get_tickets_used_by_user(user_id, party_id)
        for ticket in tickets:
            seat = ticket.occupied_seat
            if seat is None:
                continue

            seat_label = seat.label or '-'
            seat_url = None
            area = getattr(seat, 'area', None)
            if area is not None and area.slug:
                seat_url = url_for(
                    'seating.view_area',
                    slug=area.slug,
                    _anchor=f'seat-{seat.id}',
                )

            seat_data_by_user_id[user_id] = {
                'label': seat_label,
                'url': seat_url,
            }
            break

    return seat_data_by_user_id
