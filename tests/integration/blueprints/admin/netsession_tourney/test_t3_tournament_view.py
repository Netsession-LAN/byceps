"""Admin tournament detail page, match page and participant page."""

from uuid import uuid4

import pytest

from byceps.services.netsession_tourney import (
    participant_admin_service,
    stage_service,
    team_admin_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    StageType,
    TournamentMode,
)


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]


@pytest.fixture(scope='module')
def se(t3_make_tourney):
    return t3_make_tourney(StageType.single_elimination, 4)


def _html(response) -> str:
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize(
    ('tab', 'current_label'),
    [
        (None, 'Übersicht'),
        ('participants', 'Teilnehmer (4)'),
        ('stages', 'Phasen'),
        ('matches', 'Matches ('),
        ('prizes', 'Preise'),
        ('discord', 'Benachrichtigungen'),
        ('notifications', 'Benachrichtigungen'),
        ('no-such-tab', 'Übersicht'),
    ],
)
def test_view_shows_the_requested_tab(t3_client, se, tab, current_label):
    url = se.url + (f'?tab={tab}' if tab else '')

    body = _html(t3_client.get(url))

    assert se.tournament.title in body
    assert f'tabs-tab--current">{current_label}' in body


def test_view_lists_participants_and_matches(t3_client, se):
    body = _html(t3_client.get(se.url + '?tab=participants'))
    for player in se.players:
        assert player.screen_name in body

    body = _html(t3_client.get(se.url + '?tab=matches'))
    for match in se.matches():
        assert f'/matches/{match.id}' in body


def test_view_shows_dropped_participants(
    t3_client, t3_make_tourney, t3_manager
):
    tourney = t3_make_tourney(count=3, publish=False, generate=False)
    leaver = tourney.participant_of(tourney.players[0])
    participant_admin_service.remove_participant_by_admin(
        tourney.party.id,
        tourney.tournament.id,
        leaver.id,
        t3_manager,
        comment='Left the party',
    ).unwrap()

    body = _html(t3_client.get(tourney.url + '?tab=participants'))

    assert 'tabs-tab--current">Teilnehmer (2)' in body
    assert leaver.name in body


@pytest.mark.parametrize(
    'stage_id_arg', ['', 'not-a-uuid', str(uuid4()), 'own']
)
def test_view_selects_the_stage(t3_client, se, stage_id_arg):
    stage_id = str(se.stage.id) if stage_id_arg == 'own' else stage_id_arg

    body = _html(t3_client.get(se.url + f'?tab=stages&stage_id={stage_id}'))

    assert se.stage.name in body


@pytest.mark.parametrize(
    ('stage_type', 'settings'),
    [
        (StageType.swiss, {'round_count': 3}),
        (StageType.league, {}),
        (StageType.double_elimination, {}),
        (StageType.ffa_simple, {'max_players_per_match': 8}),
    ],
)
def test_view_renders_stage_types(
    t3_client, t3_make_tourney, stage_type, settings
):
    mode = (
        TournamentMode.ffa
        if stage_type == StageType.ffa_simple
        else TournamentMode.duel
    )
    tourney = t3_make_tourney(stage_type, 4, mode=mode, settings=settings)

    stages_body = _html(t3_client.get(tourney.url + '?tab=stages'))
    matches_body = _html(t3_client.get(tourney.url + '?tab=matches'))

    assert tourney.stage.name in stages_body
    assert tourney.matches()
    for match in tourney.matches():
        assert f'/matches/{match.id}' in matches_body


def test_view_without_stages(t3_client, t3_make_tourney, t3_manager):
    tourney = t3_make_tourney(publish=False, generate=False)
    stage_service.delete_stage(
        tourney.party.id, tourney.tournament.id, tourney.stage.id, t3_manager
    ).unwrap()

    body = _html(t3_client.get(tourney.url + '?tab=stages'))

    assert 'tabs-tab--current">Phasen' in body


def test_view_of_team_tournament_lists_members(
    t3_client, t3_make_tourney, t3_make_players, t3_manager
):
    tourney = t3_make_tourney(
        registration_mode=RegistrationMode.team_captain_managed,
        count=0,
        team_size=2,
        substitute_count=0,
        publish=False,
        generate=False,
    )
    captain, member = t3_make_players(tourney.party, 2)
    team = team_admin_service.create_team_by_admin(
        tourney.party.id,
        tourney.tournament.id,
        'Team Rocket',
        captain,
        t3_manager,
    ).unwrap()
    team_admin_service.add_team_member_by_admin(
        tourney.party.id, tourney.tournament.id, team.id, member, t3_manager
    ).unwrap()

    body = _html(t3_client.get(tourney.url + '?tab=participants'))
    assert 'Team Rocket' in body

    body = _html(t3_client.get(tourney.url + f'/participants/{team.id}'))
    assert 'Team Rocket' in body
    assert captain.screen_name in body
    assert member.screen_name in body
    assert 'Teammitglieder' in body


def test_participant_view(t3_client, se):
    participant = se.participant_of(se.players[0])

    body = _html(t3_client.get(se.url + f'/participants/{participant.id}'))

    assert participant.name in body
    assert 'Zurück zu Teilnehmern' in body
    assert f'/participants/{participant.id}/disqualify' in body


@pytest.mark.parametrize(
    ('query', 'back_label', 'back_tab'),
    [
        ('', 'Zurück zu Matches', 'tab=matches'),
        ('?return_to=bogus', 'Zurück zu Matches', 'tab=matches'),
        ('?return_to=stages', 'Zurück zu Phasen', 'tab=stages'),
    ],
)
def test_match_view_links_back(t3_client, se, query, back_label, back_tab):
    match = se.matches()[0]

    body = _html(t3_client.get(se.url + f'/matches/{match.id}{query}'))

    assert back_label in body
    assert back_tab in body
    assert 'Setzt oder überschreibt ein Match-Ergebnis für dieses Duell.' in (
        body
    )
    for slot in se.slots(match):
        participant = next(
            p for p in se.participants() if p.id == slot.participant_id
        )
        assert participant.name in body


def test_match_view_has_round_navigation(t3_client, se):
    first, second = se.matches()[:2]
    assert (first.round_no, second.round_no) == (1, 1)

    body = _html(t3_client.get(se.url + f'/matches/{first.id}'))

    assert f'/matches/{second.id}' in body


def test_match_view_of_ffa_match(t3_client, t3_make_tourney):
    tourney = t3_make_tourney(
        StageType.ffa_simple,
        3,
        mode=TournamentMode.ffa,
        settings={'max_players_per_match': 8},
    )
    (match,) = tourney.matches()

    body = _html(t3_client.get(tourney.url + f'/matches/{match.id}'))

    assert 'Bei FFA-Scoring-Phasen werden Ingame-Platz und Kills' in body
    assert 'placement_slot_1' in body
    assert 'FlatOut 2 Setup' not in body


@pytest.mark.parametrize(
    'path',
    [
        '/for_party/no-such-party/tournaments/{tournament_id}',
        '/for_party/{party_id}/tournaments/{random_id}',
        '/for_party/{party_id}/tournaments/{tournament_id}/matches/{random_id}',
        '/for_party/{party_id}/tournaments/{tournament_id}/participants/{random_id}',
    ],
)
def test_unknown_objects_are_not_found(t3_client, se, path):
    url = 'http://admin.acmecon.test/ns-tourneys' + path.format(
        party_id=se.party.id,
        tournament_id=se.tournament.id,
        random_id=uuid4(),
    )

    assert t3_client.get(url).status_code == 404


def test_viewer_may_look_but_not_manage(t3_viewer_client, se):
    match = se.matches()[0]

    assert t3_viewer_client.get(se.url).status_code == 200
    assert t3_viewer_client.get(
        se.url + f'/matches/{match.id}'
    ).status_code == (200)
    assert t3_viewer_client.get(se.url + '/update').status_code == 403
    assert t3_viewer_client.post(se.url + '/close').status_code == 403
    assert (
        t3_viewer_client.post(
            se.url + f'/matches/{match.id}/result',
            data={'slot_1_points': '1', 'slot_2_points': '0'},
        ).status_code
        == 403
    )


def test_anonymous_user_is_forbidden(make_client, t3_app, se):
    client = make_client(t3_app)

    assert client.get(se.url).status_code == 403
