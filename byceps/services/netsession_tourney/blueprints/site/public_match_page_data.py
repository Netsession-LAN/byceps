"""
byceps.services.netsession_tourney.blueprints.site.public_match_page_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Data loading shared by the public bracket, match list and preliminaries
pages.
"""

from __future__ import annotations

from flask import g

from byceps.services.netsession_tourney.double_grand_final import (
    get_match_results,
)
from byceps.services.netsession_tourney.match_queries import get_match_slots
from byceps.services.user import user_service

from .common import get_participants_for_tournament_indexed_by_id


def index_stages_by_id(stages) -> dict:
    return {stage.id: stage for stage in stages}


def load_match_slots_and_results(matches):
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    return slots_by_match_id, results_by_match_id


def load_match_participants_and_users(slots_by_match_id):
    participants_by_id = get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {
            slot.participant_id
            for slots in slots_by_match_id.values()
            for slot in slots
            if slot.participant_id
        },
    )
    participant_user_ids = {
        participant.user_id
        for participant in participants_by_id.values()
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(
        participant_user_ids,
        include_avatars=True,
    )
    return participants_by_id, users_by_id
