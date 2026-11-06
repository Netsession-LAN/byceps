"""A team logo is stored only for users who may use the team form."""

from io import BytesIO

from PIL import Image
from sqlalchemy import func, select

from byceps.database import db
from byceps.services.netsession_tourney import tournament_service
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyLogoAsset,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)

from tests.helpers import generate_token, http_client, log_in_user


def _png() -> BytesIO:
    buffer = BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, 'PNG')
    buffer.seek(0)
    return buffer


def test_user_without_ticket_cannot_store_a_team_logo(
    site_app, party, admin_user, make_user
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-logo-' + generate_token().lower(),
        'NS Logo',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=2,
        substitute_count=0,
    ).unwrap()
    stranger = make_user('NS_LogoStranger_' + generate_token())  # no ticket

    log_in_user(stranger.id)
    url = f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/teams/create'
    with http_client(site_app, user_id=stranger.id) as client:
        response = client.post(
            url,
            data={'name': 'Sneaky', 'logo_file': (_png(), 'logo.png')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 302

    stored = db.session.scalar(
        select(func.count())
        .select_from(DbNetsessionTourneyLogoAsset)
        .filter_by(uploaded_by_user_id=stranger.id)
    )
    assert stored == 0
