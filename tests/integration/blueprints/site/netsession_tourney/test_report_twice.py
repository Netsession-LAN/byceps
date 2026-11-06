"""Submitting the result form twice (double click, reload) must store
only one report."""

import re

from sqlalchemy import func, select

from byceps.database import db
from byceps.services.netsession_tourney import (
    match_generation,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyResultReportReceipt,
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


KEY_PATTERN = re.compile(r'name="idempotency_key" value="([^"]+)"')


def test_result_form_submitted_twice_is_stored_once(
    site_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-twice-' + generate_token().lower(),
        'NS Twice',
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
    for _ in range(2):
        player = make_user('NS_Twice_' + generate_token())
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
    match = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()[0]

    log_in_user(players[0].id)
    match_url = (
        f'http://www.acmecon.test/ns-tourneys/{tournament.slug}'
        f'/matches/{match.id}'
    )
    with http_client(site_app, user_id=players[0].id) as client:
        page = client.get(match_url)
        assert page.status_code == 200
        found = KEY_PATTERN.search(page.text)
        assert found, 'result form carries no idempotency key'

        form = {
            'slot_1_points': '2',
            'slot_2_points': '1',
            'idempotency_key': found.group(1),
        }
        for _ in range(2):
            response = client.post(match_url + '/report', data=form)
            assert response.status_code == 302

    receipt_count = db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyResultReportReceipt)
        .filter_by(match_id=match.id)
    )
    assert receipt_count == 1
