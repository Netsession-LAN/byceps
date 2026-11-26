"""Admin: the stage builder (Turnierplaner) wizard, step by step."""

import pytest

from byceps.services.netsession_tourney import stage_service
from byceps.services.netsession_tourney.blueprints.admin.route_config import (
    STAGE_BUILDER_WIZARD_SESSION_KEY,
)
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    get_stages,
    has_form_errors,
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
viewer_client = conftest_t2.viewer_client


def _builder_url(tournament, step=None):
    url = f'{tournament_path(tournament)}/stages/builder'
    return f'{url}/{step}' if step else url


def _set_state(client, tournament, state):
    with client.session_transaction() as session:
        session[STAGE_BUILDER_WIZARD_SESSION_KEY] = {
            str(tournament.party_id): {str(tournament.id): state}
        }


def _location_step(response):
    return response.headers['Location'].rsplit('/', 1)[-1]


COMPLETE_DUEL_STATE = {
    'generation_basis': 'ready',
    'main_stage_type': 'single_elimination',
    'main_stage_size': '8',
    'max_players_per_match': None,
    'use_preliminary': True,
    'preliminary_type': 'swiss',
    'round_robin_builder_mode': None,
    'round_robin_group_count': None,
    'swiss_threshold': 3,
    'match_duration_minutes': None,
    'max_matches_per_round': None,
    'break_between_rounds_minutes': 0,
}


def test_start_redirects_to_main_step(manager_client, make_tournament):
    tournament = make_tournament()

    for method in (manager_client.get, manager_client.post):
        response = method(_builder_url(tournament))
        assert response.status_code == 302
        assert _location_step(response) == 'main'


def test_wizard_requires_manage_permission(viewer_client, make_tournament):
    tournament = make_tournament()

    assert (
        viewer_client.get(_builder_url(tournament, 'main')).status_code == 403
    )
    assert (
        viewer_client.post(_builder_url(tournament, 'review')).status_code
        == 403
    )


def test_full_duel_wizard_with_round_robin(
    manager_client, make_tournament, add_players
):
    tournament = make_tournament(participant_limit=12)
    add_players(tournament, 12)

    main = manager_client.get(_builder_url(tournament, 'main'))
    assert main.status_code == 200
    assert 'Hauptturnier' in main.get_data(as_text=True)

    response = manager_client.post(
        _builder_url(tournament, 'main'),
        data={
            'generation_basis': 'ready',
            'main_stage_type': 'single_elimination',
            'main_stage_size': '8',
        },
    )
    assert _location_step(response) == 'preliminary'
    assert manager_client.get(response.headers['Location']).status_code == 200

    response = manager_client.post(
        _builder_url(tournament, 'preliminary'),
        data={
            'use_preliminary': 'y',
            'preliminary_type': 'round_robin_groups',
            'round_robin_builder_mode': 'manual_group_count',
            'round_robin_group_count': '2',
            'swiss_threshold': '3',
        },
    )
    assert _location_step(response) == 'timing'
    assert manager_client.get(response.headers['Location']).status_code == 200

    response = manager_client.post(
        _builder_url(tournament, 'timing'),
        data={'match_duration_minutes': '20', 'max_matches_per_round': '4'},
    )
    assert _location_step(response) == 'review'

    review = manager_client.get(_builder_url(tournament, 'review'))
    assert review.status_code == 200
    body = review.get_data(as_text=True)
    assert 'Aktuelle Generierungsbasis: 12 bereite Teilnehmer' in body
    assert 'Strategie: Expertenoption mit manueller Gruppenzahl' in body
    assert 'Gruppen: 2' in body
    assert 'Konkrete Verteilung: 2 Gruppen à 6' in body

    response = manager_client.post(_builder_url(tournament, 'review'))
    assert response.status_code == 302
    assert 'tab=stages' in response.headers['Location']
    stages = get_stages(tournament)
    assert pop_flashes(manager_client) == [
        f'Phasenplan wurde erstellt. {len(stages)} Phasen angelegt.'
    ]
    assert {stage.type for stage in stages} == {
        StageType.round_robin_groups,
        StageType.single_elimination,
    }
    main_stage = next(s for s in stages if s.settings['builder_role'] == 'main')
    assert main_stage.settings['match_duration_minutes'] == 20


def test_full_ffa_wizard(manager_client, make_tournament, add_players):
    tournament = make_tournament(TournamentMode.ffa, participant_limit=20)
    add_players(tournament, 10)

    main = manager_client.get(_builder_url(tournament, 'main'))
    assert main.status_code == 200
    assert 'value="ffa_single_elimination"' in main.get_data(as_text=True)

    manager_client.post(
        _builder_url(tournament, 'main'),
        data={
            'generation_basis': 'ready',
            'main_stage_type': 'ffa_single_elimination',
            'main_stage_size': '8',
            'max_players_per_match': '4',
        },
    )
    assert (
        manager_client.get(_builder_url(tournament, 'preliminary')).status_code
        == 200
    )
    manager_client.post(
        _builder_url(tournament, 'preliminary'),
        data={
            'use_preliminary': 'y',
            'preliminary_type': 'ffa_single_elimination',
        },
    )
    manager_client.post(
        _builder_url(tournament, 'timing'),
        data={'break_between_rounds_minutes': '5'},
    )

    review = manager_client.get(_builder_url(tournament, 'review'))
    body = review.get_data(as_text=True)
    assert 'Vorrunde aktiv: 10 bereite Teilnehmer starten zuerst' in body
    assert 'Heat-Größe: bis zu 4 Teilnehmer pro Match.' in body

    response = manager_client.post(_builder_url(tournament, 'review'))
    assert response.status_code == 302
    stages = get_stages(tournament)
    assert stages
    assert all(
        stage.type == StageType.ffa_single_elimination for stage in stages
    )


def test_main_step_defaults_for_ffa(manager_client, make_tournament):
    tournament = make_tournament(TournamentMode.ffa)

    response = manager_client.get(_builder_url(tournament, 'main'))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<option selected value="64">' in body


@pytest.mark.parametrize(
    ('mode', 'data', 'expected_text'),
    [
        (
            TournamentMode.duel,
            {'generation_basis': 'ready', 'main_stage_type': 'swiss'},
            'form-errors',
        ),
        (
            TournamentMode.ffa,
            {
                'generation_basis': 'ready',
                'main_stage_type': 'ffa_single_elimination',
                'main_stage_size': '8',
                'max_players_per_match': '',
            },
            'Bitte eine gültige Heat-Größe angeben.',
        ),
    ],
)
def test_main_step_rejects_invalid_input(
    manager_client, make_tournament, mode, data, expected_text
):
    tournament = make_tournament(mode)

    response = manager_client.post(_builder_url(tournament, 'main'), data=data)

    assert response.status_code == 200
    assert expected_text in page_text(response)


def test_later_steps_redirect_to_missing_step(manager_client, make_tournament):
    tournament = make_tournament()
    _set_state(manager_client, tournament, {})

    for step in ('preliminary', 'timing', 'review'):
        response = manager_client.get(_builder_url(tournament, step))
        assert _location_step(response) == 'main', step
    for step in ('preliminary', 'timing', 'review'):
        response = manager_client.post(_builder_url(tournament, step))
        assert _location_step(response) == 'main', step

    _set_state(
        manager_client,
        tournament,
        {
            **COMPLETE_DUEL_STATE,
            'use_preliminary': True,
            'preliminary_type': '',
        },
    )
    response = manager_client.get(_builder_url(tournament, 'review'))
    assert _location_step(response) == 'preliminary'

    state = dict(COMPLETE_DUEL_STATE)
    del state['break_between_rounds_minutes']
    _set_state(manager_client, tournament, state)
    response = manager_client.get(_builder_url(tournament, 'review'))
    assert _location_step(response) == 'timing'


def test_steps_render_saved_state(manager_client, make_tournament):
    tournament = make_tournament()
    _set_state(
        manager_client,
        tournament,
        {
            **COMPLETE_DUEL_STATE,
            'preliminary_type': 'round_robin_groups',
            'round_robin_builder_mode': 'manual_group_count',
            'round_robin_group_count': 4,
        },
    )

    for step in ('main', 'preliminary', 'timing'):
        response = manager_client.get(_builder_url(tournament, step))
        assert response.status_code == 200, step

    # an incomplete group count sends the admin back to the preliminary
    _set_state(
        manager_client,
        tournament,
        {
            **COMPLETE_DUEL_STATE,
            'preliminary_type': 'round_robin_groups',
            'round_robin_builder_mode': 'manual_group_count',
        },
    )
    response = manager_client.get(_builder_url(tournament, 'timing'))
    assert _location_step(response) == 'preliminary'


def test_preliminary_and_timing_steps_reject_invalid_input(
    manager_client, make_tournament
):
    tournament = make_tournament()
    _set_state(manager_client, tournament, COMPLETE_DUEL_STATE)

    response = manager_client.post(
        _builder_url(tournament, 'preliminary'),
        data={'use_preliminary': 'y', 'preliminary_type': 'league'},
    )
    assert response.status_code == 200
    assert has_form_errors(response)

    response = manager_client.post(
        _builder_url(tournament, 'timing'),
        data={'match_duration_minutes': '0'},
    )
    assert response.status_code == 200
    assert has_form_errors(response)


def test_preliminary_step_without_preliminary(manager_client, make_tournament):
    tournament = make_tournament()
    _set_state(manager_client, tournament, COMPLETE_DUEL_STATE)

    response = manager_client.post(
        _builder_url(tournament, 'preliminary'),
        data={'preliminary_type': 'swiss', 'swiss_threshold': '3'},
    )

    assert _location_step(response) == 'timing'
    with manager_client.session_transaction() as session:
        state = session[STAGE_BUILDER_WIZARD_SESSION_KEY][
            str(tournament.party_id)
        ][str(tournament.id)]
    assert state['use_preliminary'] is False
    assert state['preliminary_type'] == ''
    assert state['swiss_threshold'] is None


def test_wizard_refuses_tournament_with_stages(
    manager_client, make_tournament, manager
):
    tournament = make_tournament()
    stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        StageType.single_elimination,
        'KO',
        {},
        manager,
    ).unwrap()
    message = (
        'Der Turnierplaner arbeitet nur auf Turnieren ohne vorhandene Phasen.'
    )

    for step in ('main', 'review'):
        response = manager_client.get(_builder_url(tournament, step))
        assert response.status_code == 302
        assert 'tab=stages' in response.headers['Location']
        assert pop_flashes(manager_client) == [message]


@pytest.mark.parametrize(
    ('state_changes', 'expected_message', 'expected_step'),
    [
        (
            {'main_stage_type': 'bogus'},
            'Ungültige Daten des Turnierplaners.',
            'main',
        ),
        (
            {'max_players_per_match': 'many'},
            'Ungültige Matchgröße für den Turnierplaner.',
            'main',
        ),
        (
            {'preliminary_type': '  '},
            'Bitte ein Vorrundenformat auswählen.',
            'preliminary',
        ),
        (
            {'preliminary_type': 'bogus'},
            'Ungültiges Vorrundenformat.',
            'preliminary',
        ),
        (
            {'swiss_threshold': 9},
            'Swiss-Vorrunden benötigen eine gültige Schwelle.',
            'preliminary',
        ),
    ],
)
def test_review_submit_rejects_invalid_state(
    manager_client,
    make_tournament,
    state_changes,
    expected_message,
    expected_step,
):
    tournament = make_tournament()
    _set_state(manager_client, tournament, COMPLETE_DUEL_STATE | state_changes)

    response = manager_client.post(_builder_url(tournament, 'review'))

    assert response.status_code == 302
    assert _location_step(response) == expected_step
    assert pop_flashes(manager_client) == [expected_message]
    assert get_stages(tournament) == []


def test_review_shows_and_submits_plan_error(manager_client, make_tournament):
    tournament = make_tournament()
    _set_state(
        manager_client,
        tournament,
        COMPLETE_DUEL_STATE | {'main_stage_size': '7'},
    )

    review = manager_client.get(_builder_url(tournament, 'review'))
    assert review.status_code == 200
    assert 'Aktuelle Vorschau des Turnierplaners' in review.get_data(
        as_text=True
    )

    response = manager_client.post(_builder_url(tournament, 'review'))
    assert response.status_code == 302
    assert _location_step(response) == 'review'
    (message,) = pop_flashes(manager_client)
    assert message
    assert get_stages(tournament) == []


def test_review_without_preview_for_invalid_state(
    manager_client, make_tournament
):
    tournament = make_tournament()
    _set_state(
        manager_client,
        tournament,
        COMPLETE_DUEL_STATE | {'main_stage_type': 'bogus'},
    )

    review = manager_client.get(_builder_url(tournament, 'review'))

    assert review.status_code == 200
    assert 'Aktuelle Vorschau des Turnierplaners' not in review.get_data(
        as_text=True
    )
