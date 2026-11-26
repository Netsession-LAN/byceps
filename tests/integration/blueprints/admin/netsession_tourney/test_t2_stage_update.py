"""Admin: update a stage, change its participant source, delete it."""

import pytest

from byceps.services.netsession_tourney import stage_service
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    get_stages,
    page_text,
    pop_flashes,
    publish,
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


UNKNOWN_ID = '00000000-0000-7000-8000-000000000002'


@pytest.fixture
def duel_tournament(make_tournament):
    return make_tournament()


def _create_stage(tournament, manager, stage_type, name, settings=None):
    return stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        stage_type,
        name,
        settings or {},
        manager,
    ).unwrap()


def _stage_url(tournament, stage, action):
    return f'{tournament_path(tournament)}/stages/{stage.id}/{action}'


def test_update_form_of_swiss_stage(manager_client, duel_tournament, manager):
    stage = _create_stage(
        duel_tournament,
        manager,
        StageType.swiss,
        'Swiss',
        {'round_count': 4, 'result_report_mode': 'admin_only'},
    )

    response = manager_client.get(_stage_url(duel_tournament, stage, 'update'))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'value="Swiss"' in body
    # threshold derived from the round count
    assert '<option selected value="3">3</option>' in body


def test_update_form_of_ffa_stage(manager_client, make_tournament, manager):
    tournament = make_tournament(TournamentMode.ffa)
    stage = _create_stage(
        tournament,
        manager,
        StageType.ffa_single_elimination,
        'Heats',
        {
            'max_players_per_match': 6,
            'placement_points_rules': [
                {'from_place': 2, 'to_place': 3, 'points': 4},
                {'from_place': 1, 'to_place': 1, 'points': 9},
                {'from_place': 'x', 'to_place': 1, 'points': 1},
                'broken',
            ],
            'qualifier_top_n': 'many',
            'qualifier_selection_mode': 'weird',
        },
    )

    response = manager_client.get(_stage_url(tournament, stage, 'update'))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '1 = 9\n2-3 = 4' in body


def test_update_form_unknown_stage(manager_client, duel_tournament):
    url = f'{tournament_path(duel_tournament)}/stages/{UNKNOWN_ID}/update'

    assert manager_client.get(url).status_code == 404
    assert manager_client.post(url, data={}).status_code == 404


def test_update_stage(manager_client, duel_tournament, manager):
    first = _create_stage(
        duel_tournament, manager, StageType.round_robin_groups, 'Gruppen'
    )
    stage = _create_stage(
        duel_tournament,
        manager,
        StageType.single_elimination,
        'Alt',
        {
            'participant_source_mode': 'stage_qualifiers',
            'qualifier_source_stage_ids': [str(first.id)],
            'qualifier_top_n': 2,
        },
    )

    response = manager_client.post(
        _stage_url(duel_tournament, stage, 'update'),
        data={
            'type': 'double_elimination',
            'name': 'Neu',
            'round_count': '3',
            'group_size': '4',
            'result_report_mode': 'admin_only',
        },
    )

    assert response.status_code == 302
    assert pop_flashes(manager_client) == ['Phase wurde gespeichert.']
    updated = next(s for s in get_stages(duel_tournament) if s.id == stage.id)
    assert updated.type == StageType.double_elimination
    assert updated.name == 'Neu'
    assert updated.settings['round_count'] == 3
    assert updated.settings['group_size'] == 4
    assert updated.settings['participant_source_mode'] == 'tournament'


def test_update_rejects_invalid_form(manager_client, duel_tournament, manager):
    stage = _create_stage(
        duel_tournament, manager, StageType.single_elimination, 'KO'
    )

    response = manager_client.post(
        _stage_url(duel_tournament, stage, 'update'),
        data={'type': 'nonsense', 'name': 'KO'},
    )

    assert response.status_code == 200
    assert 'Ungültige Phasendaten.' in page_text(response)


@pytest.mark.parametrize(
    ('data', 'expected_error'),
    [
        (
            {'type': 'swiss', 'name': 'Swiss'},
            'Bitte eine Swiss-Schwelle auswählen.',
        ),
        (
            {
                'type': 'single_elimination',
                'name': 'KO',
                'participant_source_mode': 'stage_qualifiers',
                'qualifier_top_n': 'x',
            },
            'Bitte mindestens eine vorherige Phase als Quelle auswählen.',
        ),
    ],
)
def test_update_rejects_bad_settings(
    manager_client, duel_tournament, manager, data, expected_error
):
    stage = _create_stage(
        duel_tournament, manager, StageType.single_elimination, 'KO'
    )

    response = manager_client.post(
        _stage_url(duel_tournament, stage, 'update'), data=data
    )

    assert response.status_code == 200
    assert expected_error in page_text(response)
    unchanged = get_stages(duel_tournament)[0]
    assert unchanged.type == StageType.single_elimination


def test_update_and_delete_refused_after_publishing(
    manager_client, duel_tournament, add_players, manager
):
    add_players(duel_tournament, 2)
    stage = _create_stage(
        duel_tournament, manager, StageType.single_elimination, 'KO'
    )
    publish(duel_tournament, manager)

    response = manager_client.post(
        _stage_url(duel_tournament, stage, 'update'),
        data={'type': 'single_elimination', 'name': 'Umbenannt'},
    )
    assert response.status_code == 200
    assert 'Phasen lassen sich nur im Entwurf ändern.' in page_text(response)

    response = manager_client.post(_stage_url(duel_tournament, stage, 'delete'))
    assert response.status_code == 302
    assert pop_flashes(manager_client) == [
        'Phasen lassen sich nur im Entwurf ändern.'
    ]
    assert len(get_stages(duel_tournament)) == 1


def test_delete_stage(manager_client, duel_tournament, manager):
    stage = _create_stage(
        duel_tournament, manager, StageType.single_elimination, 'Weg damit'
    )

    response = manager_client.post(_stage_url(duel_tournament, stage, 'delete'))

    assert response.status_code == 302
    assert 'tab=stages' in response.headers['Location']
    assert pop_flashes(manager_client) == ['Phase wurde gelöscht.']
    assert get_stages(duel_tournament) == []


def test_delete_requires_manage_permission(
    viewer_client, duel_tournament, manager
):
    stage = _create_stage(
        duel_tournament, manager, StageType.single_elimination, 'Bleibt'
    )

    response = viewer_client.post(_stage_url(duel_tournament, stage, 'delete'))

    assert response.status_code == 403
    assert len(get_stages(duel_tournament)) == 1


def test_participant_source_update(manager_client, duel_tournament, manager):
    groups = _create_stage(
        duel_tournament, manager, StageType.round_robin_groups, 'Gruppen'
    )
    final = _create_stage(
        duel_tournament,
        manager,
        StageType.single_elimination,
        'Finale',
        {'qualifier_top_n': 4},
    )

    response = manager_client.post(
        _stage_url(duel_tournament, final, 'participant-source'),
        data={
            'participant_source_mode': 'stage_qualifiers',
            'qualifier_source_stage_ids': [str(groups.id), str(final.id)],
            'qualifier_top_n': '2',
        },
    )

    assert response.status_code == 302
    assert f'stage_id={final.id}' in response.headers['Location']
    assert pop_flashes(manager_client) == [
        'Teilnehmerquelle der Phase wurde aktualisiert.'
    ]
    updated = next(s for s in get_stages(duel_tournament) if s.id == final.id)
    assert updated.settings['participant_source_mode'] == 'stage_qualifiers'
    assert updated.settings['qualifier_source_stage_ids'] == [str(groups.id)]
    assert updated.settings['qualifier_top_n'] == 2
    assert updated.settings['qualifier_selection_mode'] == 'per_stage'


def test_participant_source_update_errors(
    manager_client, duel_tournament, add_players, manager
):
    add_players(duel_tournament, 2)
    groups = _create_stage(
        duel_tournament, manager, StageType.round_robin_groups, 'Gruppen'
    )
    url = _stage_url(duel_tournament, groups, 'participant-source')

    # the first stage has no earlier stage to take qualifiers from
    response = manager_client.post(
        url,
        data={
            'participant_source_mode': 'stage_qualifiers',
            'qualifier_source_stage_ids': [str(groups.id)],
        },
    )
    assert response.status_code == 302
    assert pop_flashes(manager_client) == [
        'Bitte mindestens eine vorherige Phase als Quelle auswählen.'
    ]

    publish(duel_tournament, manager)
    response = manager_client.post(
        url, data={'participant_source_mode': 'tournament'}
    )
    assert response.status_code == 302
    assert pop_flashes(manager_client) == [
        'Phasen lassen sich nur im Entwurf ändern.'
    ]
