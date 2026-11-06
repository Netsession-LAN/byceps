"""Check-in on the tournament page."""

from datetime import datetime, timedelta

from sqlalchemy import select, update

from byceps.database import db
from byceps.services.netsession_tourney import (
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyParticipant,
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

from tests.helpers import generate_token, http_client, log_in_user


def test_player_checks_in_on_the_tournament_page(
    site_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-checkin-view-' + generate_token().lower(),
        'NS Checkin View',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'SE',
        {},
        admin_user,
    ).unwrap()
    players = []
    for _ in range(2):
        player = make_user('NS_CheckinView_' + generate_token())
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
    now = datetime.utcnow()
    db.session.execute(
        update(DbNetsessionTourneyTournament)
        .where(DbNetsessionTourneyTournament.id == tournament.id)
        .values(
            checkin_open_at=now - timedelta(minutes=5),
            checkin_close_at=now + timedelta(minutes=10),
        )
    )
    db.session.commit()

    player = players[0]
    log_in_user(player.id)
    url = f'http://www.acmecon.test/ns-tourneys/{tournament.slug}'
    with http_client(site_app, user_id=player.id) as client:
        page = client.get(url)
        assert page.status_code == 200
        assert 'einchecken' in page.text

        response = client.post(url + '/checkin')
        assert response.status_code == 302

        page = client.get(url)
        assert 'Eingecheckt' in page.text

    checkin_state = db.session.scalar(
        select(DbNetsessionTourneyParticipant.checkin_state).filter_by(
            tournament_id=tournament.id, user_id=player.id
        )
    )
    assert checkin_state == 'checked_in'
