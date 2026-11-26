"""Fixtures and helpers for the admin tests of the stage management, the
stage builder and the stage generation (`test_t2_*`).

Import the fixtures into a test module; this is not a `conftest.py`.
"""

from __future__ import annotations

from dataclasses import replace
import html
import re
from types import SimpleNamespace

from flask import g
import pytest

from byceps.application import create_admin_app
from byceps.config.models import AdminWebAppConfig
from byceps.database import db
from byceps.services.netsession_tourney import (
    match_queries,
    participant_admin_addition,
    tournament_lifecycle_service,
    tournament_queries,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token, log_in_user


ADMIN_BASE = 'http://admin.acmecon.test/ns-tourneys'

MANAGER_PERMISSIONS = {
    'admin.access',
    'netsession_tourney.view',
    'netsession_tourney.manage',
    'netsession_tourney.admin',
}

OPEN_MATCH_STATES = {
    'ready',
    'in_progress',
    'pending_confirmation',
    'needs_admin_review',
    'disputed',
}


@pytest.fixture(scope='module')
def tourney_app(admin_app, make_byceps_config):
    """An admin app with the tournament system switched on."""
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    with admin_app.app_context():
        # The blueprint modules translate texts on import.
        g.user = SimpleNamespace(locale=None)
        app = create_admin_app(
            byceps_config, AdminWebAppConfig(server_name='admin.acmecon.test')
        )
    with app.app_context():
        yield app


@pytest.fixture(scope='module')
def manager(tourney_app, make_admin):
    manager = make_admin(MANAGER_PERMISSIONS)
    log_in_user(manager.id)
    return manager


@pytest.fixture(scope='module')
def manager_client(tourney_app, make_client, manager):
    return make_client(tourney_app, user_id=manager.id)


@pytest.fixture(autouse=True)
def _no_stale_flashes(request):
    """Start each test without messages a failed test left behind."""
    if 'manager_client' in request.fixturenames:
        pop_flashes(request.getfixturevalue('manager_client'))


@pytest.fixture(scope='module')
def viewer_client(tourney_app, make_client, make_admin):
    viewer = make_admin({'admin.access', 'netsession_tourney.view'})
    log_in_user(viewer.id)
    return make_client(tourney_app, user_id=viewer.id)


@pytest.fixture(scope='module')
def ticket_category(tourney_app, make_ticket_category, party):
    return make_ticket_category(party.id, 'T2 ' + generate_token())


@pytest.fixture(scope='module')
def make_tournament(party, manager):
    def _wrapper(mode=TournamentMode.duel, **kwargs):
        kwargs.setdefault('registration_mode', RegistrationMode.solo)
        registration_mode = kwargs.pop('registration_mode')
        return tournament_service.create_tournament(
            party.id,
            't2-' + generate_token().lower(),
            'T2 Turnier',
            mode,
            registration_mode,
            manager,
            **kwargs,
        ).unwrap()

    return _wrapper


@pytest.fixture(scope='module')
def add_players(party, manager, make_user, ticket_category):
    """Add ready players to a tournament (as the admin does).

    The users (with their tickets) are shared by the tournaments of a
    module; creating them is the expensive part.
    """
    users = []

    def _wrapper(tournament, count):
        while len(users) < count:
            user = make_user('T2_' + generate_token())
            ticket = ticket_creation_service.create_ticket(
                ticket_category, user
            )
            ticket_user_management_service.appoint_user(
                ticket.id, user, user
            ).unwrap()
            users.append(user)
        return [
            participant_admin_addition.add_user_participant_by_admin(
                party.id, tournament.id, user, manager
            ).unwrap()
            for user in users[:count]
        ]

    return _wrapper


# helpers


def tournament_path(tournament) -> str:
    return (
        f'{ADMIN_BASE}/for_party/{tournament.party_id}'
        f'/tournaments/{tournament.id}'
    )


def pop_flashes(client) -> list[str]:
    """Return (and remove) the flashed messages of the client's session."""
    with client.session_transaction() as session:
        flashes = list(session.pop('_flashes', []))
    return [str(message['text']) for _category, message in flashes]


def page_text(response) -> str:
    """Return the HTML of the response with entities resolved (messages
    flashed while rendering a form again appear in the page)."""
    return html.unescape(response.get_data(as_text=True))


def has_form_errors(response) -> bool:
    return 'form-errors' in response.get_data(as_text=True)


def publish(tournament, manager) -> None:
    tournament_lifecycle_service.publish_tournament(
        tournament.party_id, tournament.id, manager
    ).unwrap()


def get_stages(tournament) -> list:
    db.session.expire_all()
    return tournament_queries.get_stages_for_tournament(
        tournament.party_id, tournament.id
    )


def get_matches(tournament, stage=None) -> list:
    db.session.expire_all()
    matches = match_queries.get_matches_for_tournament(
        tournament.party_id, tournament.id
    )
    if stage is not None:
        matches = [match for match in matches if match.stage_id == stage.id]
    return matches


def open_duel_matches(tournament) -> list:
    matches = get_matches(tournament)
    slots_by_match_id = match_queries.get_match_slots(
        {match.id for match in matches}
    )
    return [
        match
        for match in sorted(matches, key=lambda m: (m.round_no, m.match_no))
        if match.state.value in OPEN_MATCH_STATES
        and len(
            [
                slot
                for slot in slots_by_match_id.get(match.id, [])
                if slot.participant_id is not None
            ]
        )
        >= 2
    ]


def report_open_duel_matches(client, tournament, stages=None) -> int:
    """Report a 2:1 result for every open duel match (of the stages)."""
    matches = open_duel_matches(tournament)
    if stages is not None:
        stage_ids = {stage.id for stage in stages}
        matches = [match for match in matches if match.stage_id in stage_ids]
    for match in matches:
        response = client.post(
            f'{tournament_path(tournament)}/matches/{match.id}/result',
            data={
                'slot_1_points': '2',
                'slot_2_points': '1',
                'idempotency_key': 't2-' + generate_token(),
            },
        )
        assert response.status_code == 302
    pop_flashes(client)
    return len(matches)


def generate(client, tournament, stage, data=None):
    """Submit the generation form of a stage with the values the form
    offers (automatic seeds) plus `data`."""
    url = f'{tournament_path(tournament)}/stages/{stage.id}/generate'
    form = client.get(url)
    assert form.status_code == 200, pop_flashes(client)
    return client.post(url, data=auto_seed_form_data(form) | (data or {}))


def auto_seed_form_data(response) -> dict:
    body = response.get_data(as_text=True)
    return {
        'auto_seed_participant_ids': re.findall(
            r'name="auto_seed_participant_ids" value="([^"]+)"', body
        )
    }
