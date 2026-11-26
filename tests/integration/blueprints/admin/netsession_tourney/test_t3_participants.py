"""Admin participant and team management."""

from io import BytesIO
from uuid import uuid4

from PIL import Image
import pytest

from byceps.services.netsession_tourney import registration_validation
from byceps.services.netsession_tourney.models import (
    ParticipantStatus,
    RegistrationMode,
    TeamMemberRole,
)


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]


def _post(client, url, data=None, **kwargs):
    response = client.post(url, data=data or {}, **kwargs)
    assert response.status_code == 302
    return response


@pytest.fixture(scope='module')
def draft(t3_make_tourney):
    return t3_make_tourney(count=3, publish=False, generate=False)


def test_add_participant(
    t3_client, t3_assert_flash, t3_flashes, draft, t3_make_players
):
    (newcomer,) = t3_make_players(draft.party, 1)
    url = draft.url + '/participants/add'

    response = _post(t3_client, url, {'screen_name': newcomer.screen_name})
    assert response.location.endswith('?tab=participants')
    t3_assert_flash(t3_client, 'success', 'Teilnehmer wurde hinzugefügt.')
    assert newcomer.id in {p.user_id for p in draft.participants()}

    # a second time
    _post(t3_client, url, {'screen_name': newcomer.screen_name})
    (flash,) = t3_flashes(t3_client)
    assert flash[0] == 'danger'

    _post(t3_client, url, {'screen_name': 'NoSuchUser' + str(uuid4())[:8]})
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Benutzer.')

    _post(t3_client, url, {'screen_name': 'ab'})
    t3_assert_flash(t3_client, 'danger', 'Ungültige Teilnehmerdaten.')


def test_set_seed(t3_client, t3_assert_flash, draft):
    participant = draft.participant_of(draft.players[0])
    url = draft.url + f'/participants/{participant.id}/seed'

    response = _post(t3_client, url, {'seed': '1', 'return_to': 'participant'})
    assert response.location.endswith(f'/participants/{participant.id}')
    t3_assert_flash(t3_client, 'success', 'Setzplatz wurde gespeichert.')
    assert draft.participant_of(draft.players[0]).seed == 1

    response = _post(t3_client, url, {'seed': '99'})
    assert response.location.endswith('?tab=participants')
    t3_assert_flash(
        t3_client,
        'danger',
        'Der Setzplatz darf nicht größer sein als die Zahl der aktiven '
        'Teilnehmer.',
    )

    _post(t3_client, url, {'seed': 'first'})
    t3_assert_flash(t3_client, 'danger', 'Ungültiger Setzplatz.')


def test_set_status(t3_client, t3_assert_flash, draft):
    participant = draft.participant_of(draft.players[1])
    url = draft.url + f'/participants/{participant.id}/status'

    _post(t3_client, url + '?return_to=participant', {'status': 'locked'})
    t3_assert_flash(
        t3_client, 'success', 'Status des Teilnehmers wurde gespeichert.'
    )
    assert (
        draft.participant_of(draft.players[1]).status
        == ParticipantStatus.locked
    )

    _post(t3_client, url, {'status': 'dropped'})
    t3_assert_flash(t3_client, 'danger', 'Ungültiger Status.')

    _post(
        t3_client,
        draft.url + f'/participants/{uuid4()}/status',
        {'status': 'ready'},
    )
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Teilnehmer.')


def test_disqualify_participant(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=4)
    victim = tourney.participant_of(tourney.players[0])
    url = tourney.url + f'/participants/{victim.id}/disqualify'

    _post(t3_client, url, {'reason_code': 'admin_disqualification'})
    t3_assert_flash(
        t3_client, 'danger', 'Ungültige Angaben zur Disqualifikation.'
    )

    _post(
        t3_client,
        tourney.url + f'/participants/{uuid4()}/disqualify',
        {'reason_code': 'cheating', 'comment': 'Who?'},
    )
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Teilnehmer.')

    response = _post(
        t3_client,
        url,
        {
            'reason_code': 'admin_disqualification',
            'comment': 'Cheating',
            'return_to': 'participant',
        },
    )
    assert response.location.endswith(f'/participants/{victim.id}')
    t3_assert_flash(t3_client, 'success', 'Teilnehmer wurde disqualifiziert.')
    assert victim.id not in {p.id for p in tourney.participants()}

    body = t3_client.get(tourney.url + f'/participants/{victim.id}').get_data(
        as_text=True
    )
    assert victim.name in body


def test_remove_participant(t3_client, t3_assert_flash, draft):
    participant = draft.participant_of(draft.players[2])
    url = draft.url + f'/participants/{participant.id}/remove'

    _post(t3_client, url, {'comment': '  '})
    t3_assert_flash(t3_client, 'danger', 'Bitte einen Kommentar angeben.')

    _post(t3_client, url, {'comment': 'No ticket'})
    t3_assert_flash(t3_client, 'success', 'Teilnehmer wurde entfernt.')
    assert participant.id not in {p.id for p in draft.participants()}


@pytest.fixture(scope='module')
def team_tourney(t3_make_tourney):
    return t3_make_tourney(
        registration_mode=RegistrationMode.team_captain_managed,
        count=0,
        team_size=2,
        substitute_count=1,
        publish=False,
        generate=False,
    )


def _team(tourney, name):
    return next(p for p in tourney.participants() if p.name == name)


def _roles(team):
    members = registration_validation.get_team_members_for_participants(
        {team.id}
    ).get(team.id, [])
    return {member.user_id: member.role for member in members}


def _png() -> BytesIO:
    buffer = BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, 'PNG')
    buffer.seek(0)
    return buffer


def test_create_team(
    t3_client, t3_assert_flash, t3_flashes, team_tourney, t3_make_players
):
    captain, other = t3_make_players(team_tourney.party, 2)
    url = team_tourney.url + '/teams/create'

    response = _post(
        t3_client,
        url,
        {
            'name': 'Logo Lords',
            'captain_screen_name': captain.screen_name,
            'logo_file': (_png(), 'lords.png'),
        },
        content_type='multipart/form-data',
    )
    assert response.location.endswith('?tab=participants')
    t3_assert_flash(t3_client, 'success', 'Team wurde angelegt.')
    team = _team(team_tourney, 'Logo Lords')
    assert team.manager_user_id == captain.id
    assert team.logo_url
    assert _roles(team) == {captain.id: TeamMemberRole.captain}

    _post(t3_client, url, {'name': 'Plain', 'captain_screen_name': 'x'})
    t3_assert_flash(t3_client, 'danger', 'Ungültige Teamdaten.')

    _post(
        t3_client,
        url,
        {'name': 'Ghosts', 'captain_screen_name': 'Ghost' + str(uuid4())[:8]},
    )
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Benutzer.')

    _post(
        t3_client,
        url,
        {
            'name': 'Broken Logo',
            'captain_screen_name': other.screen_name,
            'logo_file': (BytesIO(b'not an image'), 'logo.png'),
        },
        content_type='multipart/form-data',
    )
    (flash,) = t3_flashes(t3_client)
    assert flash[0] == 'danger'
    assert 'Broken Logo' not in {p.name for p in team_tourney.participants()}

    # captain of another team already
    _post(
        t3_client,
        url,
        {'name': 'Twice', 'captain_screen_name': captain.screen_name},
    )
    (flash,) = t3_flashes(t3_client)
    assert flash[0] == 'danger'


def test_team_members_and_captain(
    t3_client, t3_assert_flash, team_tourney, t3_make_players
):
    captain, mate, sub = t3_make_players(team_tourney.party, 3)
    _post(
        t3_client,
        team_tourney.url + '/teams/create',
        {'name': 'Crew', 'captain_screen_name': captain.screen_name},
    )
    t3_assert_flash(t3_client, 'success', 'Team wurde angelegt.')
    team = _team(team_tourney, 'Crew')
    team_url = team_tourney.url + f'/teams/{team.id}'

    for member in (mate, sub):
        response = _post(
            t3_client,
            team_url + '/members/add',
            {'screen_name': member.screen_name, 'return_to': 'participant'},
        )
        assert response.location.endswith(f'/participants/{team.id}')
        t3_assert_flash(t3_client, 'success', 'Teammitglied wurde hinzugefügt.')
    assert set(_roles(team)) == {captain.id, mate.id, sub.id}

    _post(t3_client, team_url + '/members/add', {'screen_name': 'zz'})
    t3_assert_flash(t3_client, 'danger', 'Ungültige Daten zum Teammitglied.')
    _post(
        t3_client,
        team_url + '/members/add',
        {'screen_name': 'Nobody' + str(uuid4())[:8]},
    )
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Benutzer.')

    _post(
        t3_client,
        team_tourney.url + f'/teams/{uuid4()}/members/add',
        {'screen_name': sub.screen_name},
    )
    t3_assert_flash(t3_client, 'danger', 'Unbekanntes Team.')

    _post(t3_client, team_url + '/captain', {'member_user_id': 'captain'})
    t3_assert_flash(t3_client, 'danger', 'Ungültiges Team-Mitglied.')
    _post(t3_client, team_url + '/captain', {'member_user_id': str(mate.id)})
    t3_assert_flash(t3_client, 'success', 'Teamkapitän wurde geändert.')
    assert _roles(team)[mate.id] == TeamMemberRole.captain
    _post(t3_client, team_url + '/captain', {'member_user_id': str(uuid4())})
    t3_assert_flash(t3_client, 'danger', 'Unbekanntes Teammitglied.')

    _post(t3_client, team_url + f'/members/{mate.id}/remove')
    t3_assert_flash(
        t3_client,
        'danger',
        'Der Captain kann nicht aus dem Team entfernt werden.',
    )
    _post(t3_client, team_url + f'/members/{captain.id}/remove')
    t3_assert_flash(t3_client, 'success', 'Teammitglied wurde entfernt.')
    assert captain.id not in _roles(team)


@pytest.mark.parametrize(
    'path',
    [
        '/participants/add',
        '/participants/{random}/seed',
        '/participants/{random}/status',
        '/participants/{random}/disqualify',
        '/participants/{random}/remove',
        '/teams/create',
        '/teams/{random}/members/add',
        '/teams/{random}/members/{random}/remove',
        '/teams/{random}/captain',
    ],
)
def test_unknown_tournament_is_not_found(t3_client, draft, path):
    url = (
        'http://admin.acmecon.test/ns-tourneys'
        f'/for_party/{draft.party.id}/tournaments/{uuid4()}'
        + path.format(random=uuid4())
    )

    assert t3_client.post(url, data={}).status_code == 404
