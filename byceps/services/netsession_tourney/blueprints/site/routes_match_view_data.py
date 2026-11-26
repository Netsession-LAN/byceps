"""
byceps.services.netsession_tourney.blueprints.site.routes_match_view_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Data loading and preparation for the match page.
"""

from __future__ import annotations

from datetime import timedelta

from flask import g

from byceps.services.netsession_tourney.match_chat_service import (
    can_user_access_match_chat,
    get_match_chat_messages,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots_for_match,
    get_match_timeline_entries,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import (
    MatchState,
    ParticipantType,
)
from byceps.services.netsession_tourney.registration_validation import (
    get_team_members_for_participants,
)
from byceps.services.netsession_tourney.result_report_mode import (
    is_stage_result_reporting_admin_only,
)
from byceps.services.user import user_service

from .builder_helpers import get_materialized_builder_container_stages
from .common import get_participants_for_tournament_indexed_by_id
from .public_match_page_data import load_match_slots_and_results
from .routes_match_flatout2_data import (
    find_current_host_name as find_current_host_name,
    get_flatout2_round_details as get_flatout2_round_details,
)
from .user_state_helpers import can_user_report_match_result


def load_tournament_matches_with_slots_and_results(tournament):
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id, results_by_match_id = load_match_slots_and_results(
        matches
    )
    return matches, slots_by_match_id, results_by_match_id


def get_sorted_match_slots(match_id) -> list:
    return sorted(
        get_match_slots_for_match(match_id), key=lambda slot: slot.slot_no
    )


def find_bye_slot_ids(match, slots) -> set:
    bye_slot_ids = set()
    for slot in slots:
        if _is_explicit_bye_slot(match, slot):
            bye_slot_ids.add(slot.id)
    return bye_slot_ids


def _is_explicit_bye_slot(match, slot) -> bool:
    return (
        slot.participant_id is None
        and slot.source_match_slot_id is None
        and match.state == MatchState.completed
    )


def load_slot_participants(slots) -> dict:
    return get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {slot.participant_id for slot in slots if slot.participant_id},
    )


def load_match_activity(tournament, match, participants_by_id):
    """Return timeline entries, chat messages, chat team per actor user
    ID, and the users involved.
    """
    timeline_entries = get_match_timeline_entries(
        g.party.id, tournament.id, match.id
    )
    timeline_actor_ids = {
        entry['actor_user_id']
        for entry in timeline_entries
        if entry['actor_user_id']
    }
    chat_messages = get_match_chat_messages(g.party.id, tournament.id, match.id)
    chat_actor_ids = {message.actor_user_id for message in chat_messages}
    members_by_participant_id = get_team_members_for_participants(
        set(participants_by_id.keys())
    )
    chat_team_by_actor_user_id = _build_chat_team_by_actor_user_id(
        participants_by_id, members_by_participant_id
    )

    users_by_id = user_service.get_users_indexed_by_id(
        timeline_actor_ids | chat_actor_ids, include_avatars=True
    )
    return (
        timeline_entries,
        chat_messages,
        chat_team_by_actor_user_id,
        users_by_id,
    )


def _build_chat_team_by_actor_user_id(
    participants_by_id, members_by_participant_id
) -> dict:
    chat_team_by_actor_user_id = {}
    for participant in participants_by_id.values():
        if participant.type is not ParticipantType.team:
            continue

        _add_team_chat_actors(
            chat_team_by_actor_user_id, participant, members_by_participant_id
        )
    return chat_team_by_actor_user_id


def _add_team_chat_actors(
    chat_team_by_actor_user_id: dict, participant, members_by_participant_id
) -> None:
    if participant.manager_user_id is not None:
        chat_team_by_actor_user_id.setdefault(
            participant.manager_user_id, participant
        )

    for member in members_by_participant_id.get(participant.id, []):
        chat_team_by_actor_user_id.setdefault(member.user_id, participant)


def build_activity_items(timeline_entries, chat_messages) -> list[dict]:
    activity_items = [
        {
            'kind': 'event',
            'created_at': entry['created_at'],
            'entry': entry,
        }
        for entry in timeline_entries
    ] + [
        {
            'kind': 'chat',
            'created_at': message.created_at,
            'message': message,
        }
        for message in chat_messages
    ]
    activity_items.sort(key=lambda item: item['created_at'])
    return activity_items


def determine_match_user_permissions(
    tournament, match, slots, participants_by_id, stages_by_id
) -> tuple[bool, bool]:
    """Return whether the current user may report a result and chat."""
    can_report = False
    can_chat = False
    user = getattr(g, 'user', None)
    if user is not None and user.authenticated:
        is_admin_or_referee = is_user_admin_or_referee(user)
        can_report = can_user_report_match_result(
            user.id,
            tournament,
            match,
            slots,
            participants_by_id,
            is_admin_or_referee=False,
            admin_only=is_stage_result_reporting_admin_only(
                stages_by_id.get(match.stage_id)
            ),
        )
        can_chat = can_user_access_match_chat(
            g.party.id,
            tournament.id,
            match.id,
            user.id,
            is_admin_or_referee=is_admin_or_referee,
        )
    return can_report, can_chat


def is_user_admin_or_referee(user):
    return user.has_permission('netsession_tourney.manage') or (
        user.has_permission('netsession_tourney.admin')
    )


def is_ffa_detail_match(is_ffa_scoring_match, is_flatout2_match):
    return is_ffa_scoring_match or is_flatout2_match


def compute_match_end_at(match, stage_duration_minutes):
    return (
        match.scheduled_at + timedelta(minutes=stage_duration_minutes)
        if match.scheduled_at is not None and stage_duration_minutes is not None
        else None
    )


def shows_preliminaries_tab(stages, is_flatout2_tournament) -> bool:
    return (
        bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament
    )
