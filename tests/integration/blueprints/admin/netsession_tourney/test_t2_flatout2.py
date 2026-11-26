"""Admin: prepare a FlatOut 2 stage by hand with the generation form."""

import pytest

from byceps.services.netsession_tourney import stage_service
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_TRACK_CHOICES_BY_MODE,
    FLATOUT2_VEHICLE_CHOICES_BY_MODE,
)
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
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


TRACK = FLATOUT2_TRACK_CHOICES_BY_MODE['single_race'][0]
VEHICLE = FLATOUT2_VEHICLE_CHOICES_BY_MODE['single_race'][0]
DERBY_TRACK = FLATOUT2_TRACK_CHOICES_BY_MODE['single_derby'][0]


@pytest.fixture
def setup(make_tournament, add_players, manager):
    return _make_setup(make_tournament, add_players, manager)


@pytest.fixture(scope='module')
def shared_setup(make_tournament, add_players, manager):
    """Like `setup`, for tests that leave the stage unchanged."""
    return _make_setup(make_tournament, add_players, manager)


def _make_setup(make_tournament, add_players, manager):
    """A FlatOut 2 stage with 6 players, at most 4 per match."""
    tournament = make_tournament(TournamentMode.ffa, game='FlatOut 2')
    players = add_players(tournament, 6)
    stage = _create_stage(tournament, manager, {'max_players_per_match': 4})
    url = f'{tournament_path(tournament)}/stages/{stage.id}/generate'
    return tournament, players, stage, url


def _create_stage(tournament, manager, settings, name='FlatOut 2'):
    return stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        StageType.ffa_flatout2_single_elimination,
        name,
        settings,
        manager,
    ).unwrap()


def _form_data(players) -> dict:
    """Two matches with two races: players 1-3 and 4-6."""
    data = {
        'flatout2_match_count_round_1': '2',
        'flatout2_race_count_round_1': '2',
        'flatout2_mode_round_1_race_1': 'single_race',
        'flatout2_track_round_1_race_1': TRACK,
        'flatout2_vehicle_round_1_race_1': VEHICLE,
        'flatout2_mode_round_1_race_2': 'single_derby',
        'flatout2_track_round_1_race_2': DERBY_TRACK,
        'flatout2_vehicle_round_1_race_2': VEHICLE,
    }
    for index, player in enumerate(players):
        match_no, slot_no = divmod(index, 3)
        key = f'flatout2_participant_round_1_match_{match_no + 1}_slot_{slot_no + 1}'
        data[key] = str(player.id)
    return data


def test_form_shows_round_configuration(manager_client, shared_setup):
    _, players, _, url = shared_setup

    response = manager_client.get(url)

    assert response.status_code == 200
    body = page_text(response)
    assert 'name="flatout2_match_count_round_1"' in body
    assert 'name="flatout2_participant_round_1_match_1_slot_4"' in body
    assert 'name="flatout2_participant_round_1_match_1_slot_5"' not in body
    for player in players:
        assert player.name in body


def test_prepare_stage(manager_client, setup):
    tournament, players, stage, url = setup
    data = _form_data(players) | {'round_starts_at_round_1': '2026-12-24T20:00'}

    response = manager_client.post(url, data=data)

    assert response.status_code == 302
    assert f'stage_id={stage.id}' in response.headers['Location']
    matches = get_matches(tournament, stage)
    assert len(matches) == 2
    assert pop_flashes(manager_client) == ['2 Matches wurden erzeugt.']
    assert {match.scheduled_at.hour for match in matches} == {19}
    (saved,) = get_stages(tournament)
    (round_config,) = saved.settings['flatout2_rounds']
    assert round_config['match_count'] == 2
    assert [race['mode'] for race in round_config['races']] == [
        'single_race',
        'single_derby',
    ]
    blueprint = saved.settings['flatout2_match_blueprints']['1:2']
    assert blueprint['host_participant_id'] == str(players[3].id)

    # the form shows the saved configuration again
    body = page_text(manager_client.get(url))
    assert f'data-selected-value="{DERBY_TRACK}"' in body
    view = manager_client.get(f'{tournament_path(tournament)}?tab=stages')
    assert 'Phase neu vorbereiten' in page_text(view)


def _change(players, **changes) -> dict:
    data = _form_data(players)
    for key, value in changes.items():
        data[key] = value.format(*[str(player.id) for player in players])
    return data


@pytest.mark.parametrize(
    ('changes', 'expected_error'),
    [
        (
            {'flatout2_match_count_round_1': '0'},
            'Bitte für Runde 1 eine Matchanzahl zwischen 1 und 10 wählen.',
        ),
        (
            {'flatout2_race_count_round_1': 'elf'},
            'Bitte für Runde 1 eine Rennanzahl zwischen 1 und 10 wählen.',
        ),
        (
            {'flatout2_mode_round_1_race_2': 'drift'},
            'Bitte für Runde 1, Rennen 2 einen gültigen Modus wählen.',
        ),
        (
            {'flatout2_track_round_1_race_1': DERBY_TRACK},
            'Bitte für Runde 1, Rennen 1 eine passende Strecke wählen.',
        ),
        (
            {'flatout2_vehicle_round_1_race_1': 'Bobbycar'},
            'Bitte für Runde 1, Rennen 1 ein gültiges Fahrzeug wählen.',
        ),
        (
            {'flatout2_participant_round_1_match_1_slot_2': 'nobody'},
            'Die Teilnehmerzuordnung für Runde 1, Match 1 ist ungültig.',
        ),
        (
            {'flatout2_participant_round_1_match_1_slot_2': '{0}'},
            'Ein Teilnehmer darf in Runde 1, Match 1 nur einmal vorkommen.',
        ),
        (
            {'flatout2_participant_round_1_match_2_slot_4': '{0}'},
            'Ein Teilnehmer darf in Runde 1 nur einem Match zugewiesen sein.',
        ),
        (
            {'flatout2_participant_round_1_match_2_slot_1': ''},
            'In Runde 1, Match 2 muss Slot 1 belegt sein, '
            'da Slot 1 immer der Host ist.',
        ),
        (
            {'round_starts_at_round_1': 'morgen'},
            'Ungültiger Startzeitpunkt für Runde 1.',
        ),
    ],
)
def test_prepare_stage_rejects_invalid_input(
    manager_client, shared_setup, changes, expected_error
):
    tournament, players, stage, url = shared_setup

    response = manager_client.post(url, data=_change(players, **changes))

    assert response.status_code == 200
    body = page_text(response)
    assert expected_error in body
    # the posted configuration is shown again
    assert f'data-selected-value="{DERBY_TRACK}"' in body
    assert get_matches(tournament, stage) == []


def test_stage_hints_and_saved_defaults(
    manager_client, make_tournament, add_players, manager
):
    tournament = make_tournament(TournamentMode.ffa, game='FlatOut 2')
    players = add_players(tournament, 3)
    final = _create_stage(
        tournament,
        manager,
        {
            'max_players_per_match': 'viele',
            'flatout2_rounds': [
                {'round_no': 'x', 'match_count': 'y'},
                'kaputt',
            ],
            # races saved per match blueprint, as older versions did
            'flatout2_match_blueprints': {
                '1:1': {
                    'races': [
                        {'mode': 'single_stunt', 'track': 'X', 'vehicle': 'Y'},
                        'kaputt',
                    ],
                    'participant_ids': [str(players[1].id), None],
                },
            },
        },
        name='Finale',
    )
    _create_stage(tournament, manager, {'round_count': 3}, name='Drei Runden')
    _create_stage(tournament, manager, {'round_count': 'x'}, name='Offen')

    view = manager_client.get(f'{tournament_path(tournament)}?tab=stages')

    body = page_text(view)
    assert 'besteht aus einem einzelnen Finale' in body
    assert 'Konfiguriert: 3 Runden.' in body
    assert 'Lege Runden, Matches, Rennen, Hosts und Teilnehmer direkt' in body

    form = manager_client.get(
        f'{tournament_path(tournament)}/stages/{final.id}/generate'
    )
    assert form.status_code == 200
    body = page_text(form)
    assert 'data-selected-value="X"' in body
    assert 'name="flatout2_participant_round_1_match_1_slot_8"' in body
