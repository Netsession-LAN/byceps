"""Admin: generate the matches of every stage format via the generation
form."""

import pytest

from byceps.services.netsession_tourney import stage_service
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    generate,
    get_matches,
    get_stages,
    page_text,
    pop_flashes,
    tournament_path,
)


# shared fixtures
_no_stale_flashes = conftest_t2._no_stale_flashes
add_players = conftest_t2.add_players
make_tournament = conftest_t2.make_tournament
manager = conftest_t2.manager
manager_client = conftest_t2.manager_client
ticket_category = conftest_t2.ticket_category
tourney_app = conftest_t2.tourney_app


PLACEMENT_POINTS = [
    {'from_place': 1, 'to_place': 1, 'points': 10},
    {'from_place': 2, 'to_place': 4, 'points': 3},
]


@pytest.mark.parametrize(
    ('mode', 'stage_type', 'settings', 'player_count'),
    [
        (TournamentMode.duel, StageType.double_elimination, {}, 6),
        (
            TournamentMode.duel,
            StageType.double_elimination_double_grand_final,
            {},
            5,
        ),
        (
            TournamentMode.duel,
            StageType.round_robin_groups,
            {'group_size': 4},
            8,
        ),
        (TournamentMode.duel, StageType.league, {'round_count': 2}, 5),
        (
            TournamentMode.duel,
            StageType.swiss,
            {'swiss_threshold': 2, 'round_count': 3},
            7,
        ),
        (
            TournamentMode.ffa,
            StageType.ffa_simple,
            {'placement_points_rules': PLACEMENT_POINTS},
            10,
        ),
        (
            TournamentMode.ffa,
            StageType.ffa_single_elimination,
            {
                'max_players_per_match': 4,
                'placement_points_rules': PLACEMENT_POINTS,
            },
            13,
        ),
    ],
)
def test_generate_stage_format(
    manager_client,
    make_tournament,
    add_players,
    manager,
    mode,
    stage_type,
    settings,
    player_count,
):
    tournament = make_tournament(mode)
    add_players(tournament, player_count)
    stage = stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        stage_type,
        'Phase',
        settings,
        manager,
    ).unwrap()

    response = generate(manager_client, tournament, stage)

    assert response.status_code == 302
    assert 'tab=stages' in response.headers['Location']
    matches = get_matches(tournament)
    assert matches
    assert pop_flashes(manager_client) == [
        f'{len(get_matches(tournament, stage))} Matches wurden erzeugt.'
    ]


def test_stage_overview_lists_stages(manager_client, make_tournament, manager):
    tournament = make_tournament()
    for stage_type, name in [
        (StageType.round_robin_groups, 'Gruppenphase'),
        (StageType.single_elimination, 'Finalrunde'),
    ]:
        stage_service.create_stage(
            tournament.party_id, tournament.id, stage_type, name, {}, manager
        ).unwrap()

    response = manager_client.get(f'{tournament_path(tournament)}?tab=stages')

    assert response.status_code == 200
    body = page_text(response)
    assert 'Gruppenphase' in body
    assert 'Finalrunde' in body
    assert 'Setzliste / Matches generieren' in body
    assert len(get_stages(tournament)) == 2
