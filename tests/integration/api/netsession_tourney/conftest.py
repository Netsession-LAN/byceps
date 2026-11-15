"""Fixtures for the Netsession tournament API."""

from dataclasses import replace

import pytest

from byceps.application import create_api_app
from byceps.config.models import ApiWebAppConfig
from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID
from byceps.services.netsession_tourney import (
    match_generation,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import RegistrationMode
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


@pytest.fixture(scope='module')
def ns_api_client(admin_app, make_byceps_config):
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    app = create_api_app(
        byceps_config, ApiWebAppConfig(server_name='api.ns.test')
    )
    return app.test_client()


@pytest.fixture(scope='module')
def read_headers(admin_user):
    token = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_api.read')}
    )
    return {'Authorization': f'Bearer {token.token}'}


@pytest.fixture(scope='module')
def other_headers(admin_user):
    token = authn_api_service.create_api_token(admin_user.id, set())
    return {'Authorization': f'Bearer {token.token}'}


@pytest.fixture
def make_live_tourney(
    admin_app, make_party, brand, admin_user, make_user, make_ticket_category
):
    """A live tournament with `count` solo players and one generated stage."""

    def _wrapper(mode, stage_type, count, settings=None):
        party = make_party(brand)
        tournament = tournament_service.create_tournament(
            party.id,
            'ns-api-' + generate_token().lower(),
            'NS API ' + stage_type.value,
            mode,
            RegistrationMode.solo,
            admin_user,
        ).unwrap()
        stage = stage_service.create_stage(
            party.id,
            tournament.id,
            stage_type,
            'Stage',
            settings or {},
            admin_user,
        ).unwrap()
        category = make_ticket_category(party.id, 'NS-API-' + generate_token())
        for no in range(count):
            player = make_user(f'NS_Api_{no}_' + generate_token())
            ticket = ticket_creation_service.create_ticket(category, player)
            ticket_user_management_service.appoint_user(
                ticket.id, player, player
            ).unwrap()
            registration_service.register_user(
                party.id, tournament.id, player
            ).unwrap()
        tournament_lifecycle_service.publish_tournament(
            party.id, tournament.id, admin_user
        ).unwrap()
        match_generation.generate_stage_matches(
            party.id, tournament.id, stage.id, admin_user
        ).unwrap()
        return party, tournament

    return _wrapper
