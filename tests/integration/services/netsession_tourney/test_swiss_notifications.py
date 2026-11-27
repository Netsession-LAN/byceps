"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from sqlalchemy import select

from byceps.database import db
from byceps.services.netsession_tourney import (
    match_generation,
    match_queries,
    registration_service,
    result_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyNotification,
)
from byceps.services.netsession_tourney.models import (
    MatchState,
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


def test_swiss_announces_ready_matches_of_every_follow_up_round(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    """Seeding round 2 of a three-round Swiss stage used to drop the IDs
    of the newly ready matches, so their players were never notified."""
    tournament, stage = _create_swiss_tournament(party, admin_user, 3)
    for _ in range(4):
        _register_player(
            party.id, tournament.id, make_user, make_ticket_category
        )
    assert tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    assert match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).is_ok()

    for match in _ready_matches(party.id, tournament.id, round_no=1):
        _report_slot_1_as_winner(party.id, tournament.id, match.id, admin_user)

    round_2_matches = _ready_matches(party.id, tournament.id, round_no=2)
    assert round_2_matches
    announced_match_ids = _get_announced_match_ids(tournament.id)
    assert {str(match.id) for match in round_2_matches} <= announced_match_ids


def _create_swiss_tournament(party, admin_user, round_count):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-swiss-notify-' + generate_token().lower(),
        'NS Swiss Notify',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.swiss,
        'Swiss',
        {'round_count': round_count},
        admin_user,
    ).unwrap()
    return tournament, stage


def _register_player(party_id, tournament_id, make_user, make_ticket_category):
    player = make_user('NS_SwissNotify_' + generate_token())
    category = make_ticket_category(party_id, 'NS-Ticket-' + generate_token())
    ticket = ticket_creation_service.create_ticket(category, player)
    assert ticket_user_management_service.appoint_user(
        ticket.id, player, player
    ).is_ok()
    assert registration_service.register_user(
        party_id, tournament_id, player
    ).is_ok()


def _ready_matches(party_id, tournament_id, *, round_no):
    return [
        match
        for match in match_queries.get_matches_for_tournament(
            party_id, tournament_id
        )
        if match.round_no == round_no and match.state == MatchState.ready
    ]


def _report_slot_1_as_winner(party_id, tournament_id, match_id, admin_user):
    assert result_service.report_result(
        party_id,
        tournament_id,
        match_id,
        admin_user.id,
        idempotency_key='swiss-notify-' + generate_token(),
        winner_slot=1,
        score={'display': '1:0'},
        actor_is_admin_or_referee=True,
        admin_comment='Test Swiss notifications',
    ).is_ok()


def _get_announced_match_ids(tournament_id) -> set[str]:
    payloads = db.session.scalars(
        select(DbNetsessionTourneyNotification.payload_json)
        .filter_by(tournament_id=tournament_id)
        .filter_by(kind='match_ready')
    ).all()
    return {payload['match_id'] for payload in payloads}
