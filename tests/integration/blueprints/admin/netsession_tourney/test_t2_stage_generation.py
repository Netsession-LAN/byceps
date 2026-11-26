"""Admin: the generation form of a stage, seeds and round start times."""

import pytest

from byceps.services.netsession_tourney import (
    stage_service,
    tournament_lifecycle_service,
    tournament_queries,
)
from byceps.services.netsession_tourney.models import StageType

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    auto_seed_form_data,
    get_matches,
    page_text,
    pop_flashes,
    publish,
    report_open_duel_matches,
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


UNKNOWN_ID = '00000000-0000-7000-8000-000000000003'


@pytest.fixture
def setup(make_tournament, add_players, manager):
    return _make_setup(make_tournament, add_players, manager)


@pytest.fixture(scope='module')
def shared_setup(make_tournament, add_players, manager):
    """Like `setup`, for tests that leave the stage unchanged."""
    return _make_setup(make_tournament, add_players, manager)


def _make_setup(make_tournament, add_players, manager):
    """A duel tournament with a single elimination stage and 6 players."""
    tournament = make_tournament()
    players = add_players(tournament, 6)
    stage = stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        StageType.single_elimination,
        'KO',
        {'match_duration_minutes': 30},
        manager,
    ).unwrap()
    url = f'{tournament_path(tournament)}/stages/{stage.id}/generate'
    return tournament, players, stage, url


def _participants(tournament):
    return tournament_queries.get_participants_for_tournament(
        tournament.party_id, tournament.id
    )


def test_form_lists_seeds_and_round_starts(manager_client, shared_setup):
    tournament, players, _, url = shared_setup

    response = manager_client.get(url)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for player in players:
        assert f'name="manual_seed_{player.id}"' in body
        assert player.name in body
    assert 'name="round_starts_at_round_1"' in body
    assert 'name="round_starts_at_round_3"' in body


def test_form_requires_manage_permission(viewer_client, shared_setup):
    *_, url = shared_setup

    assert viewer_client.get(url).status_code == 403
    assert viewer_client.post(url).status_code == 403


def test_form_unknown_stage(manager_client, shared_setup):
    tournament, *_ = shared_setup
    url = f'{tournament_path(tournament)}/stages/{UNKNOWN_ID}/generate'

    assert manager_client.get(url).status_code == 404
    assert manager_client.post(url).status_code == 404


def test_generate_with_manual_seed_and_round_start(manager_client, setup):
    tournament, players, stage, url = setup
    data = auto_seed_form_data(manager_client.get(url))
    top_seed = players[3]

    response = manager_client.post(
        url,
        data=data
        | {
            f'manual_seed_{top_seed.id}': '1',
            f'manual_seed_{players[0].id}': ' ',
            'round_starts_at_round_1': '2026-12-24T18:00',
            'round_starts_at_round_2': '',
            'round_starts_at_round_x': 'ignored',
            'round_starts_at_round_0': 'ignored',
        },
    )

    assert response.status_code == 302
    assert f'stage_id={stage.id}' in response.headers['Location']
    matches = get_matches(tournament, stage)
    assert pop_flashes(manager_client) == [
        f'{len(matches)} Matches wurden erzeugt.'
    ]
    assert len([m for m in matches if m.round_no == 1]) == 4
    seeds = {p.id: p.seed for p in _participants(tournament)}
    assert seeds[top_seed.id] == 1
    assert sorted(seeds.values()) == [1, 2, 3, 4, 5, 6]
    first_round = [m for m in matches if m.round_no == 1]
    # 18:00 in Berlin is 17:00 UTC
    assert {m.scheduled_at.hour for m in first_round if m.scheduled_at} == {17}


@pytest.mark.parametrize(
    ('auto_seeds', 'expected_error'),
    [
        (
            'none',
            'Die Teilnehmerliste hat sich geändert. '
            'Bitte die Setzlisten-Seite neu laden.',
        ),
        ('invalid', 'Ungültige Zuordnung der automatischen Setzplätze.'),
        ('unknown', 'Die Teilnehmerliste hat sich geändert.'),
        ('duplicate', 'Die Liste der automatischen Setzplätze ist ungültig.'),
    ],
)
def test_generate_rejects_bad_auto_seeds(
    manager_client, shared_setup, auto_seeds, expected_error
):
    tournament, players, stage, url = shared_setup
    ids = [str(player.id) for player in players]
    auto_seed_ids = {
        'none': [],
        'invalid': ['nope'],
        'unknown': [UNKNOWN_ID],
        'duplicate': ids[:1] + ids,
    }[auto_seeds]

    response = manager_client.post(
        url, data={'auto_seed_participant_ids': auto_seed_ids}
    )

    assert response.status_code == 200
    assert expected_error in page_text(response)
    assert get_matches(tournament, stage) == []
    assert 'name="auto_seed_participant_ids"' in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ('field', 'value', 'expected_error'),
    [
        (
            'manual_seed_{player}',
            'x',
            'Manuelle Setzplätze müssen Zahlen sein.',
        ),
        (
            'manual_seed_{player}',
            '0',
            'Manuelle Setzplätze müssen bei 1 beginnen.',
        ),
        ('manual_seed_garbage', '1', 'Ungültige Eingabe des Setzplatzes.'),
        (
            'manual_seed_' + UNKNOWN_ID,
            '1',
            'Die Teilnehmerliste hat sich geändert.',
        ),
        (
            'manual_seed_{player}',
            '2',
            'Manuelle Setzplätze müssen lückenlos bei 1 beginnen '
            'und dürfen keine Duplikate enthalten.',
        ),
        (
            'round_starts_at_round_2',
            'gestern',
            'Ungültiger Startzeitpunkt für Runde 2.',
        ),
    ],
)
def test_generate_rejects_bad_manual_input(
    manager_client, shared_setup, field, value, expected_error
):
    tournament, players, stage, url = shared_setup
    data = auto_seed_form_data(manager_client.get(url))
    data[field.format(player=players[0].id)] = value

    response = manager_client.post(url, data=data)

    assert response.status_code == 200
    assert expected_error in page_text(response)
    assert get_matches(tournament, stage) == []


def test_generation_blocked_after_reported_result(
    manager_client, setup, manager
):
    tournament, _, stage, url = setup
    publish(tournament, manager)
    assert (
        manager_client.post(
            url, data=auto_seed_form_data(manager_client.get(url))
        ).status_code
        == 302
    )
    pop_flashes(manager_client)
    assert report_open_duel_matches(manager_client, tournament) > 0

    for method in (manager_client.get, manager_client.post):
        response = method(url)
        assert response.status_code == 302
        assert f'stage_id={stage.id}' in response.headers['Location']
        (message,) = pop_flashes(manager_client)
        assert message.startswith(
            'In dieser Phase gibt es schon gemeldete Ergebnisse.'
        )


def test_generation_blocked_for_canceled_tournament(
    manager_client, setup, manager
):
    tournament, _, stage, url = setup
    tournament_lifecycle_service.cancel_tournament(
        tournament.party_id, tournament.id, manager
    ).unwrap()

    response = manager_client.get(url)

    assert response.status_code == 302
    assert pop_flashes(manager_client) == [
        'Abgeschlossene oder abgesagte Turniere lassen sich nicht neu erzeugen.'
    ]


def test_form_with_too_few_participants(
    manager_client, make_tournament, add_players, manager
):
    tournament = make_tournament()
    add_players(tournament, 1)
    stage = stage_service.create_stage(
        tournament.party_id,
        tournament.id,
        StageType.single_elimination,
        'KO',
        {},
        manager,
    ).unwrap()
    url = f'{tournament_path(tournament)}/stages/{stage.id}/generate'

    response = manager_client.get(url)

    assert response.status_code == 302
    assert f'stage_id={stage.id}' in response.headers['Location']
    (message,) = pop_flashes(manager_client)
    assert message


def _create_stage(tournament, manager, stage_type, name, settings):
    return stage_service.create_stage(
        tournament.party_id, tournament.id, stage_type, name, settings, manager
    ).unwrap()


def test_qualifier_stage_blocked_until_source_is_complete(
    manager_client, make_tournament, add_players, manager
):
    tournament = make_tournament()
    add_players(tournament, 4)
    groups = _create_stage(
        tournament, manager, StageType.round_robin_groups, 'Gruppen', {}
    )
    final = _create_stage(
        tournament,
        manager,
        StageType.single_elimination,
        'Finale',
        {
            'participant_source_mode': 'stage_qualifiers',
            'qualifier_source_stage_ids': [str(groups.id)],
            'qualifier_top_n': 2,
        },
    )
    base = f'{tournament_path(tournament)}/stages'
    final_url = f'{base}/{final.id}/generate'

    manager_client.get(final_url)
    assert pop_flashes(manager_client) == [
        'Phase "Gruppen" hat noch keine generierten Matches.'
    ]

    groups_url = f'{base}/{groups.id}/generate'
    manager_client.post(
        groups_url, data=auto_seed_form_data(manager_client.get(groups_url))
    )
    pop_flashes(manager_client)
    publish(tournament, manager)
    manager_client.get(final_url)
    assert pop_flashes(manager_client) == [
        'Phase "Gruppen" ist noch nicht abgeschlossen.'
    ]

    while report_open_duel_matches(manager_client, tournament):
        pass
    response = manager_client.get(final_url)
    assert response.status_code == 200
    response = manager_client.post(
        final_url, data=auto_seed_form_data(response)
    )
    assert response.status_code == 302
    assert pop_flashes(manager_client) == ['1 Matches wurden erzeugt.']


def test_qualifier_stage_without_sources_is_blocked(
    manager_client, make_tournament, add_players, manager
):
    tournament = make_tournament()
    add_players(tournament, 2)
    stage = _create_stage(
        tournament,
        manager,
        StageType.single_elimination,
        'Finale',
        {'participant_source_mode': 'stage_qualifiers'},
    )

    manager_client.get(
        f'{tournament_path(tournament)}/stages/{stage.id}/generate'
    )

    assert pop_flashes(manager_client) == [
        'Qualifikationsphasen fehlen. Konfiguriere zuerst die Vorrunden-Quelle.'
    ]
