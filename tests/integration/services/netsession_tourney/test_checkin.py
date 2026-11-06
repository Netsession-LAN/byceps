"""Optional check-in: only checked-in participants get into the bracket."""

from datetime import datetime, timedelta

from sqlalchemy import update

from byceps.database import db
from byceps.services.netsession_tourney import (
    checkin_service,
    match_generation,
    match_queries,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyTournament,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


def _tournament_with_players(
    party, admin_user, make_user, make_ticket_category, n
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-checkin-' + generate_token().lower(),
        'NS Checkin',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'SE',
        {'include_consolation_final': False},
        admin_user,
    ).unwrap()
    players = []
    for _ in range(n):
        player = make_user('NS_Checkin_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(ticket.id, player, player)
        assert registration_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
        players.append(player)
    assert tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    return tournament, stage, players


def _set_window(tournament_id, open_offset_min, close_offset_min):
    now = datetime.utcnow()
    db.session.execute(
        update(DbNetsessionTourneyTournament)
        .where(DbNetsessionTourneyTournament.id == tournament_id)
        .values(
            checkin_open_at=now + timedelta(minutes=open_offset_min),
            checkin_close_at=now + timedelta(minutes=close_offset_min),
        )
    )
    db.session.commit()


def test_only_checked_in_players_get_into_the_bracket(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stage, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 3
    )
    _set_window(tournament.id, -5, 10)

    for player in players[:2]:
        assert checkin_service.check_in(party.id, tournament.id, player).is_ok()

    # still open: no generation yet
    blocked = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert blocked.is_err()
    assert 'Check-in läuft noch' in blocked.unwrap_err()

    _set_window(tournament.id, -15, -1)
    assert checkin_service.check_in(
        party.id, tournament.id, players[2]
    ).is_err()

    matches = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()
    slots = match_queries.get_match_slots({m.id for m in matches})
    seated = {
        slot.participant_id
        for match_slots in slots.values()
        for slot in match_slots
        if slot.participant_id
    }
    assert len(seated) == 2


def test_check_in_needs_an_open_window_and_a_registration(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, _, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 2
    )

    assert checkin_service.check_in(
        party.id, tournament.id, players[0]
    ).is_err()

    _set_window(tournament.id, 5, 30)
    assert checkin_service.check_in(
        party.id, tournament.id, players[0]
    ).is_err()

    _set_window(tournament.id, -5, 30)
    stranger = make_user('NS_Stranger_' + generate_token())
    assert checkin_service.check_in(party.id, tournament.id, stranger).is_err()
    assert checkin_service.check_in(party.id, tournament.id, players[0]).is_ok()
