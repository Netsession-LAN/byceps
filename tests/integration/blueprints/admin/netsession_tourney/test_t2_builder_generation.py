"""Admin: stages created by the stage builder (Turnierplaner): their meta
boxes, generation summaries and generating them in order."""

import pytest

from byceps.services.netsession_tourney import stage_builder_service
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.integration.blueprints.admin.netsession_tourney import conftest_t2
from tests.integration.blueprints.admin.netsession_tourney.conftest_t2 import (
    generate,
    get_matches,
    get_stages,
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


@pytest.fixture(scope='module')
def build_plan(manager):
    def _wrapper(tournament, main_stage_type, main_stage_size, **kwargs):
        kwargs.setdefault('max_players_per_match', None)
        kwargs.setdefault('preliminary_type', None)
        kwargs.setdefault('round_robin_builder_mode', None)
        kwargs.setdefault('round_robin_group_count', None)
        kwargs.setdefault('swiss_threshold', None)
        return stage_builder_service.build_stage_builder_plan(
            tournament.party_id,
            tournament.id,
            generation_basis='ready',
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            match_duration_minutes=None,
            max_matches_per_round=None,
            break_between_rounds_minutes=None,
            initiator=manager,
            **kwargs,
        ).unwrap()

    return _wrapper


def _by_role(tournament, role):
    return [
        stage
        for stage in get_stages(tournament)
        if stage.settings.get('builder_role') == role
    ]


def _page(client, tournament, stage, action):
    response = client.get(
        f'{tournament_path(tournament)}/stages/{stage.id}/{action}'
    )
    assert response.status_code == 200, pop_flashes(client)
    return page_text(response)


def test_round_robin_preliminary_before_generation(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament()
    add_players(tournament, 12)
    build_plan(
        tournament,
        StageType.single_elimination,
        8,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='manual_group_count',
        round_robin_group_count=2,
    )
    (preliminary,) = _by_role(tournament, 'preliminary')
    (main,) = _by_role(tournament, 'main')

    body = _page(manager_client, tournament, preliminary, 'update')
    assert 'Turnierplaner: Vorrunden-Übersicht' in body
    assert 'Qualifikation: gleich viele pro Gruppe' in body
    assert 'Teilnehmerbasis: Bereit' in body

    body = _page(manager_client, tournament, main, 'update')
    assert 'Turnierplaner: Hauptturnier' in body
    assert 'Teilnehmerquelle: automatische Qualifikation' in body
    assert 'Größe des Hauptturniers: 8' in body

    body = _page(manager_client, tournament, preliminary, 'generate')
    assert 'Strategie: Expertenoption mit manueller Gruppenzahl' in body
    assert 'Manuell vorgegeben: 2 Gruppen' in body
    assert 'Konkrete Verteilung: 2 Gruppen à 6' in body
    assert 'Globale Rundensicht: Runde 1: 6 Matches' in body

    response = manager_client.get(f'{tournament_path(tournament)}?tab=stages')
    assert response.status_code == 200, pop_flashes(manager_client)


def test_round_robin_preliminary_then_main_stage(
    manager_client, make_tournament, add_players, build_plan, manager
):
    tournament = make_tournament()
    add_players(tournament, 12)
    build_plan(
        tournament,
        StageType.single_elimination,
        8,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='standard',
    )
    (preliminary,) = _by_role(tournament, 'preliminary')
    (main,) = _by_role(tournament, 'main')

    response = generate(manager_client, tournament, preliminary)

    assert response.status_code == 302
    groups = _by_role(tournament, 'preliminary_group')
    assert len(groups) >= 2
    first_group = min(groups, key=lambda stage: stage.order_no)
    assert f'stage_id={first_group.id}' in response.headers['Location']
    pop_flashes(manager_client)

    body = _page(manager_client, tournament, first_group, 'update')
    assert 'Turnierplaner: Vorrunden-Gruppe A' in body
    assert 'Teilnehmerquelle: feste Gruppenzuweisung' in body
    body = _page(manager_client, tournament, preliminary, 'update')
    assert 'bereits in echte Gruppenphasen materialisiert' in body
    view = manager_client.get(f'{tournament_path(tournament)}?tab=stages')
    assert 'Vorrunde Gruppe A' in page_text(view)

    publish(tournament, manager)
    while report_open_duel_matches(manager_client, tournament, groups):
        pass

    body = _page(manager_client, tournament, main, 'generate')
    assert 'manual_seed_' not in body
    response = generate(manager_client, tournament, main)
    assert response.status_code == 302
    main_matches = get_matches(tournament, main)
    assert main_matches
    assert pop_flashes(manager_client) == [
        f'{len(main_matches)} Matches wurden erzeugt.'
    ]


def test_swiss_preliminary(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament()
    add_players(tournament, 10)
    build_plan(
        tournament,
        StageType.double_elimination,
        8,
        preliminary_type=StageType.swiss,
        swiss_threshold=2,
    )
    (preliminary,) = _by_role(tournament, 'preliminary')

    body = _page(manager_client, tournament, preliminary, 'update')
    assert 'Turnierplaner: Vorrunde' in body
    assert 'Swiss qualifiziert über die Gesamttabelle ins Hauptturnier.' in body

    body = _page(manager_client, tournament, preliminary, 'generate')
    assert 'Qualifikation: Top 8 insgesamt aus Swiss ins Hauptturnier' in body

    response = generate(manager_client, tournament, preliminary)
    assert response.status_code == 302
    assert get_matches(tournament, preliminary)


def test_unneeded_preliminary_is_skipped(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament()
    add_players(tournament, 6)
    build_plan(
        tournament,
        StageType.single_elimination,
        8,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='standard',
    )
    (main,) = _by_role(tournament, 'main')

    body = _page(manager_client, tournament, main, 'generate')
    assert 'Die Vorrunde ist aktuell nicht nötig.' in body

    response = generate(manager_client, tournament, main)
    assert response.status_code == 302
    assert get_matches(tournament, main)


def test_main_stage_without_preliminary(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament()
    add_players(tournament, 4)
    build_plan(tournament, StageType.double_elimination, 8)
    (main,) = get_stages(tournament)

    body = _page(manager_client, tournament, main, 'update')
    assert 'Teilnehmerquelle: direkte bereite Teilnehmer' in body
    body = _page(manager_client, tournament, main, 'generate')
    assert (
        'Dieses Hauptturnier wird direkt aus bereiten Teilnehmern erzeugt.'
        in body
    )


def test_ffa_builder_stages(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament(TournamentMode.ffa)
    add_players(tournament, 20)
    build_plan(
        tournament,
        StageType.ffa_single_elimination,
        8,
        max_players_per_match=4,
        preliminary_type=StageType.ffa_single_elimination,
    )
    stages = get_stages(tournament)
    assert len(stages) >= 2

    view = manager_client.get(f'{tournament_path(tournament)}?tab=stages')
    assert view.status_code == 200
    for stage in stages:
        body = _page(manager_client, tournament, stage, 'update')
        assert 'Turnierplaner' in body

    first = min(stages, key=lambda stage: stage.order_no)
    response = generate(manager_client, tournament, first)
    assert response.status_code == 302
    assert get_matches(tournament)


def test_flatout2_builder_stages(
    manager_client, make_tournament, add_players, build_plan
):
    tournament = make_tournament(TournamentMode.ffa, game='FlatOut 2')
    add_players(tournament, 24)
    build_plan(
        tournament,
        StageType.ffa_flatout2_single_elimination,
        8,
        max_players_per_match=8,
        preliminary_type=StageType.ffa_flatout2_single_elimination,
    )
    stages = get_stages(tournament)
    assert len(stages) >= 2
    assert {stage.type for stage in stages} == {
        StageType.ffa_flatout2_single_elimination
    }

    view = manager_client.get(f'{tournament_path(tournament)}?tab=stages')
    assert view.status_code == 200
    assert 'FlatOut-2-Phase' in page_text(view)
    for stage in stages:
        body = _page(manager_client, tournament, stage, 'update')
        assert 'Turnierplaner' in body
