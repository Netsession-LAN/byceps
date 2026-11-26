"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney import (
    tournament_category_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)

from tests.helpers import generate_token, http_client


def test_anonymous_user_can_view_tournaments_and_details(
    site_app, party, admin_user
):
    create_result = tournament_service.create_tournament(
        party.id,
        'ns-public-' + generate_token().lower(),
        'NS Public Visibility',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    with http_client(site_app) as client:
        index_response = client.get('http://www.acmecon.test/ns-tourneys/')
        open_matches_response = client.get(
            'http://www.acmecon.test/ns-tourneys/open-matches'
        )
        detail_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}'
        )
        bracket_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/bracket'
        )
        matches_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/matches'
        )
        ranking_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/ranking'
        )
        participants_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/participants'
        )
        rules_response = client.get(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/rules'
        )

    assert index_response.status_code == 200
    assert open_matches_response.status_code == 200
    assert tournament.title in index_response.text
    assert detail_response.status_code == 200
    assert bracket_response.status_code == 200
    assert matches_response.status_code == 200
    assert ranking_response.status_code == 200
    assert participants_response.status_code == 200
    assert rules_response.status_code == 302  # no rules: back to overview
    assert tournament.title in detail_response.text


def test_tournaments_are_grouped_by_category_on_index(
    site_app, party, admin_user
):
    main_category_result = (
        tournament_category_service.create_tournament_category(
            party.id, 'Hauptturnier'
        )
    )
    assert main_category_result.is_ok()
    main_category = main_category_result.unwrap()

    side_category_result = (
        tournament_category_service.create_tournament_category(
            party.id, 'Nebenturnier'
        )
    )
    assert side_category_result.is_ok()
    side_category = side_category_result.unwrap()

    main_tourney_result = tournament_service.create_tournament(
        party.id,
        'ns-main-ui-' + generate_token().lower(),
        'Main UI Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        category_id=main_category.id,
    )
    assert main_tourney_result.is_ok()

    side_tourney_result = tournament_service.create_tournament(
        party.id,
        'ns-side-ui-' + generate_token().lower(),
        'Side UI Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        category_id=side_category.id,
    )
    assert side_tourney_result.is_ok()

    with http_client(site_app) as client:
        response = client.get('http://www.acmecon.test/ns-tourneys/')

    assert response.status_code == 200
    assert 'Hauptturnier' in response.text
    assert 'Nebenturnier' in response.text
    assert response.text.index('Hauptturnier') < response.text.index(
        'Nebenturnier'
    )


def test_anonymous_user_cannot_register(site_app, party, admin_user):
    create_result = tournament_service.create_tournament(
        party.id,
        'ns-anon-register-' + generate_token().lower(),
        'NS Anonymous Register Forbidden',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    with http_client(site_app) as client:
        response = client.post(
            f'http://www.acmecon.test/ns-tourneys/{tournament.slug}/register'
        )

    assert response.status_code in (302, 403)
