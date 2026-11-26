"""Admin: create, update and delete a single stage with the stage form."""

import pytest

from byceps.services.netsession_tourney import stage_service
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    get_stages,
    page_text,
    pop_flashes,
    tournament_path,
)


# shared fixtures
_no_stale_flashes = conftest_t2._no_stale_flashes
make_tournament = conftest_t2.make_tournament
manager = conftest_t2.manager
manager_client = conftest_t2.manager_client
ticket_category = conftest_t2.ticket_category
tourney_app = conftest_t2.tourney_app
viewer_client = conftest_t2.viewer_client


def _create(manager_client, tournament, **data):
    data.setdefault('result_report_mode', 'both_must_confirm')
    return manager_client.post(
        f'{tournament_path(tournament)}/stages', data=data
    )


def _create_stage(tournament, manager, stage_type, name, settings=None):
    return stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        stage_type,
        name,
        settings or {},
        manager,
    ).unwrap()


def test_create_form(manager_client, make_tournament):
    tournament = make_tournament()

    response = manager_client.get(
        f'{tournament_path(tournament)}/stages/create'
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'value="single_elimination"' in body
    assert 'value="ffa_simple"' not in body


def test_create_form_requires_manage_permission(viewer_client, make_tournament):
    tournament = make_tournament()

    response = viewer_client.get(f'{tournament_path(tournament)}/stages/create')

    assert response.status_code == 403


def test_create_form_unknown_tournament_and_party(manager_client, party):
    base = 'http://admin.acmecon.test/ns-tourneys/for_party'
    tournament_id = '00000000-0000-7000-8000-000000000001'

    assert (
        manager_client.get(
            f'{base}/{party.id}/tournaments/{tournament_id}/stages/create'
        ).status_code
        == 404
    )
    assert (
        manager_client.get(
            f'{base}/no-such-party/tournaments/{tournament_id}/stages/create'
        ).status_code
        == 404
    )


def test_create_swiss_stage(manager_client, make_tournament):
    tournament = make_tournament()

    response = _create(
        manager_client,
        tournament,
        type='swiss',
        name='Schweizer System',
        swiss_threshold='3',
        match_duration_minutes='30',
        max_matches_per_round='4',
        break_between_rounds_minutes='5',
    )

    assert response.status_code == 302
    assert 'tab=stages' in response.headers['Location']
    assert pop_flashes(manager_client) == ['Phase wurde angelegt.']
    (stage,) = get_stages(tournament)
    assert stage.type == StageType.swiss
    assert stage.name == 'Schweizer System'
    assert stage.settings['swiss_threshold'] == 3
    assert stage.settings['round_count'] == 5
    assert stage.settings['match_duration_minutes'] == 30
    assert stage.settings['max_matches_per_round'] == 4
    assert stage.settings['break_between_rounds_minutes'] == 5
    assert stage.settings['participant_source_mode'] == 'tournament'


def test_create_ffa_stage_with_placement_points(
    manager_client, make_tournament
):
    tournament = make_tournament(TournamentMode.ffa)

    response = _create(
        manager_client,
        tournament,
        type='ffa_single_elimination',
        name='Heats',
        max_players_per_match='4',
        placement_points='Platz 1 = 10 Punkte\n\n2: 6\n3-4 -> 2 pts',
        points_per_kill='2',
        max_matches_per_round='3',
    )

    assert response.status_code == 302
    (stage,) = get_stages(tournament)
    assert stage.settings['placement_points_rules'] == [
        {'from_place': 1, 'to_place': 1, 'points': 10},
        {'from_place': 2, 'to_place': 2, 'points': 6},
        {'from_place': 3, 'to_place': 4, 'points': 2},
    ]
    assert stage.settings['points_per_kill'] == 2
    assert stage.settings['max_players_per_match'] == 4
    assert stage.settings['result_report_mode'] == 'admin_only'
    assert 'max_matches_per_round' not in stage.settings


@pytest.mark.parametrize(
    ('placement_points', 'expected_error'),
    [
        ('', 'Bitte für dieses FFA-Format ein Platz-zu-Punkte-Schema angeben.'),
        ('1 = 10\nerster', 'Ungültiges Platz-zu-Punkte-Schema in Zeile 2.'),
        ('0 = 10', 'Plätze müssen in Zeile 1 bei 1 oder höher liegen.'),
        ('3-2 = 10', 'Der Platzbereich in Zeile 1 ist ungültig.'),
        ('1 = 1000', 'Die Punkte in Zeile 1 müssen zwischen 0 und 999 liegen.'),
        (
            '1-3 = 5\n2 = 4',
            'Platzbereiche im FFA-Schema dürfen sich nicht überlappen.',
        ),
    ],
)
def test_create_ffa_stage_rejects_bad_placement_points(
    manager_client, make_tournament, placement_points, expected_error
):
    tournament = make_tournament(TournamentMode.ffa, participant_limit=12)

    response = _create(
        manager_client,
        tournament,
        type='ffa_simple',
        name='Lobbys',
        placement_points=placement_points,
    )

    assert response.status_code == 200
    assert expected_error in page_text(response)
    assert get_stages(tournament) == []


def test_create_rejects_invalid_form(manager_client, make_tournament):
    tournament = make_tournament()

    response = _create(manager_client, tournament, type='swiss', name='')

    assert response.status_code == 200
    assert 'Ungültige Phasendaten.' in page_text(response)
    assert get_stages(tournament) == []


def test_create_swiss_requires_threshold(manager_client, make_tournament):
    tournament = make_tournament()

    response = _create(manager_client, tournament, type='swiss', name='Swiss')

    assert response.status_code == 200
    assert 'Bitte eine Swiss-Schwelle auswählen.' in page_text(response)


@pytest.mark.parametrize(
    ('source_data', 'expected_error'),
    [
        ({'participant_source_mode': 'lottery'}, 'Ungültige Teilnehmerquelle.'),
        (
            {
                'participant_source_mode': 'stage_qualifiers',
                'qualifier_selection_mode': 'random',
            },
            'Ungültiger Qualifikationsmodus.',
        ),
        (
            {
                'participant_source_mode': 'stage_qualifiers',
                'qualifier_source_stage_ids': ['not-a-uuid'],
                'qualifier_top_n': '3',
                'qualifier_selection_mode': 'per_group',
            },
            'Bitte mindestens eine vorherige Phase als Quelle auswählen.',
        ),
    ],
)
def test_create_rejects_bad_participant_source(
    manager_client, make_tournament, source_data, expected_error
):
    tournament = make_tournament()

    response = _create(
        manager_client,
        tournament,
        type='single_elimination',
        name='KO',
        **source_data,
    )

    assert response.status_code == 200
    assert expected_error in page_text(response)
    assert get_stages(tournament) == []


def test_create_with_qualifiers_from_earlier_stage(
    manager_client, make_tournament, manager
):
    tournament = make_tournament()
    groups = _create_stage(
        tournament, manager, StageType.round_robin_groups, 'Gruppen'
    )

    response = _create(
        manager_client,
        tournament,
        type='single_elimination',
        name='Finale',
        participant_source_mode='stage_qualifiers',
        qualifier_source_stage_ids=[str(groups.id), str(groups.id)],
        qualifier_top_n='2',
        qualifier_selection_mode='per_group',
    )

    assert response.status_code == 302
    final = next(
        stage for stage in get_stages(tournament) if stage.id != groups.id
    )
    assert final.settings['participant_source_mode'] == 'stage_qualifiers'
    assert final.settings['qualifier_source_stage_ids'] == [str(groups.id)]
    assert final.settings['qualifier_top_n'] == 2
    assert final.settings['qualifier_selection_mode'] == 'per_group'


def test_create_rejects_top_n_out_of_range_and_keeps_input(
    manager_client, make_tournament, manager
):
    tournament = make_tournament()
    groups = _create_stage(
        tournament, manager, StageType.round_robin_groups, 'Gruppen'
    )

    response = _create(
        manager_client,
        tournament,
        type='single_elimination',
        name='Finale',
        participant_source_mode='stage_qualifiers',
        qualifier_source_stage_ids=[str(groups.id)],
        qualifier_top_n='129',
        qualifier_selection_mode='per_group',
    )

    assert response.status_code == 200
    body = page_text(response)
    assert 'Top N muss zwischen 1 und 128 liegen.' in body
    assert 'value="129"' in body
    assert len(get_stages(tournament)) == 1
