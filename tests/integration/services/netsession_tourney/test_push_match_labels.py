"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

import pytest

from byceps.services.netsession_tourney import (
    match_generation,
    match_queries,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.browser_push_outbox_match_label import (
    build_browser_push_match_label,
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


@pytest.mark.parametrize(
    'stage_type',
    [
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    ],
)
@pytest.mark.parametrize('player_count', [4, 5, 8])
def test_double_elimination_push_labels_name_the_bracket(
    admin_app,
    party,
    admin_user,
    make_user,
    make_ticket_category,
    stage_type,
    player_count,
):
    """Push and Discord DM labels of double elimination matches used to
    fall back to the plain match number, because the stage type was
    compared with enum members instead of their values."""
    tournament = _create_live_tournament(
        party,
        admin_user,
        make_user,
        make_ticket_category,
        stage_type,
        player_count,
    )

    matches = match_queries.get_matches_for_tournament(party.id, tournament.id)
    labels = [
        build_browser_push_match_label({'match_id': str(match.id)})
        for match in matches
    ]

    assert labels
    assert all(
        label.startswith(('WB', 'LB', 'Grand Final', 'Double Grand Final'))
        for label in labels
    ), labels
    assert any(label.startswith('LB') for label in labels)


def _create_live_tournament(
    party, admin_user, make_user, make_ticket_category, stage_type, player_count
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-de-labels-' + generate_token().lower(),
        'NS DE Labels',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id, tournament.id, stage_type, 'Main', {}, admin_user
    ).unwrap()
    for _ in range(player_count):
        player = make_user('NS_DeLabels_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        assert ticket_user_management_service.appoint_user(
            ticket.id, player, player
        ).is_ok()
        assert registration_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    assert tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    assert match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).is_ok()
    return tournament
