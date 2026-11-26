"""Admin: the preview on the review step of the stage builder
(Turnierplaner) for different formats and numbers of players."""

import pytest

from byceps.services.netsession_tourney.blueprints.admin.route_config import (
    STAGE_BUILDER_WIZARD_SESSION_KEY,
)
from byceps.services.netsession_tourney.models import TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    page_text,
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


DUEL = {
    'generation_basis': 'ready',
    'main_stage_type': 'single_elimination',
    'main_stage_size': '8',
    'max_players_per_match': None,
    'use_preliminary': False,
    'preliminary_type': '',
    'round_robin_builder_mode': None,
    'round_robin_group_count': None,
    'swiss_threshold': None,
    'break_between_rounds_minutes': 0,
}

FFA = DUEL | {
    'main_stage_type': 'ffa_single_elimination',
    'max_players_per_match': 4,
}


@pytest.mark.parametrize(
    ('mode', 'player_count', 'state', 'expected_lines'),
    [
        (
            TournamentMode.duel,
            1,
            DUEL,
            ['Noch keine 2 bereiten Teilnehmer'],
        ),
        (
            TournamentMode.duel,
            4,
            DUEL,
            [
                'Mit der aktuellen Anzahl bereiter Teilnehmer ist keine Vorrunde nötig.'
            ],
        ),
        (
            TournamentMode.duel,
            10,
            DUEL,
            [
                'Ohne Vorrunde würde die spätere Generierung des Hauptturniers blockieren.'
            ],
        ),
        (
            TournamentMode.duel,
            10,
            DUEL
            | {
                'use_preliminary': True,
                'preliminary_type': 'swiss',
                'swiss_threshold': 2,
            },
            [
                'Swiss-Vorrunde: Schwelle 2/2, 3 Runden, Qualifikation Top 8 insgesamt'
            ],
        ),
        (
            TournamentMode.duel,
            16,
            DUEL
            | {
                'use_preliminary': True,
                'preliminary_type': 'round_robin_groups',
                'round_robin_builder_mode': 'standard',
            },
            [
                'Strategie: Empfohlener Standard',
                'Qualifikation: Top',
                'Vorrunden-Matches insgesamt',
            ],
        ),
        (
            TournamentMode.ffa,
            12,
            FFA,
            [
                'würde das Hauptturnier noch blockieren: 12 Teilnehmer',
                'Aktiviere eine Vorrunde oder erhöhe die Zielgröße',
            ],
        ),
        (
            TournamentMode.ffa,
            6,
            FFA,
            [
                'Das Hauptturnier startet direkt mit 6 bereiten Teilnehmern.',
                'FFA Single Elimination: Die Qualifikanten je Heat',
                'Vorschau Hauptturnier:',
                'Matches im Hauptturnier im aktuellen Preview',
            ],
        ),
        (
            TournamentMode.ffa,
            12,
            FFA
            | {
                'main_stage_type': 'ffa_flatout2_single_elimination',
                'max_players_per_match': 6,
                'use_preliminary': True,
                'preliminary_type': 'ffa_flatout2_single_elimination',
            },
            [
                'starten zuerst in FlatOut 2.',
                'FlatOut 2: Top 3 je Heat qualifizieren sich',
                'Vorrunden-Preview:',
                'Vorrunden-Matches im aktuellen Preview',
            ],
        ),
    ],
)
def test_review_preview_lines(
    manager_client,
    make_tournament,
    add_players,
    mode,
    player_count,
    state,
    expected_lines,
):
    tournament = make_tournament(mode)
    add_players(tournament, player_count)
    with manager_client.session_transaction() as session:
        session[STAGE_BUILDER_WIZARD_SESSION_KEY] = {
            str(tournament.party_id): {str(tournament.id): state}
        }

    response = manager_client.get(
        f'{tournament_path(tournament)}/stages/builder/review'
    )

    assert response.status_code == 200
    body = page_text(response)
    assert (
        f'Aktuelle Generierungsbasis: {player_count} bereite Teilnehmer' in body
    )
    for line in expected_lines:
        assert line in body
