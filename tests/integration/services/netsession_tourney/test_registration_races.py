"""Registrations that happen at the same time must not overrun the
participant limit, and a self-service captain gets a registration row."""

import threading
import time

from sqlalchemy import func, select, update

from byceps.database import db
from byceps.services.netsession_tourney import (
    registration_service,
    team_captain_service,
    tournament_service,
    tourney_registration_checks,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneyTournament,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


def _player(party, make_user, make_ticket_category):
    player = make_user('NS_Race_' + generate_token())
    category = make_ticket_category(party.id, 'NS-Ticket-' + generate_token())
    ticket = ticket_creation_service.create_ticket(category, player)
    ticket_user_management_service.appoint_user(ticket.id, player, player)
    return player


def test_simultaneous_registrations_respect_the_participant_limit(
    admin_app, party, admin_user, make_user, make_ticket_category, monkeypatch
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-race-' + generate_token().lower(),
        'NS Race',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    db.session.execute(
        update(DbNetsessionTourneyTournament)
        .where(DbNetsessionTourneyTournament.id == tournament.id)
        .values(participant_limit=1, registration_open=True)
    )
    db.session.commit()
    players = [
        _player(party, make_user, make_ticket_category) for _ in range(2)
    ]

    # Make the race certain: both requests count before either inserts.
    original_count = (
        tourney_registration_checks.count_active_participants_for_tournament
    )

    def slow_count(*args, **kwargs):
        count = original_count(*args, **kwargs)
        time.sleep(0.5)
        return count

    monkeypatch.setattr(
        tourney_registration_checks,
        'count_active_participants_for_tournament',
        slow_count,
    )

    results = []

    def register(player):
        with admin_app.app_context():
            results.append(
                registration_service.register_user(
                    party.id, tournament.id, player
                )
            )
            db.session.remove()

    threads = [threading.Thread(target=register, args=(p,)) for p in players]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result.is_ok() for result in results) == 1
    participant_count = db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament.id)
    )
    assert participant_count == 1


def test_self_service_captain_gets_a_registration(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-captain-reg-' + generate_token().lower(),
        'NS Captain Reg',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=2,
        substitute_count=0,
    ).unwrap()
    captain = _player(party, make_user, make_ticket_category)

    assert team_captain_service.create_team_for_captain(
        party.id, tournament.id, captain, 'Race Team'
    ).is_ok()

    registration_count = db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyRegistration)
        .filter_by(tournament_id=tournament.id, user_id=captain.id)
    )
    assert registration_count == 1
