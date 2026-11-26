"""Admin results of FFA and FlatOut 2 matches, FlatOut 2 host."""

import pytest

from byceps.database import db
from byceps.services.netsession_tourney import double_grand_final
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_TRACK_CHOICES_BY_MODE,
    FLATOUT2_VEHICLE_CHOICES_BY_MODE,
)
from byceps.services.netsession_tourney.models import (
    MatchState,
    StageType,
    TournamentMode,
)


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]

PLACEMENT_POINTS_RULES = [
    'not a rule',
    {'from_place': 'first', 'to_place': 1, 'points': 99},
    {'from_place': 1, 'to_place': 1, 'points': 10},
    {'from_place': 2, 'to_place': 3, 'points': 5},
]


def _post(client, url, data=None):
    response = client.post(url, data=data or {})
    assert response.status_code == 302
    return response


def _result(match):
    db.session.expire_all()
    return double_grand_final.get_match_results({match.id}).get(match.id)


def _ffa_data(slots, placements, kills):
    data = {}
    for slot, placement, kill_count in zip(
        slots, placements, kills, strict=True
    ):
        data[f'placement_slot_{slot.slot_no}'] = placement
        data[f'kills_slot_{slot.slot_no}'] = kill_count
    return data


@pytest.fixture(scope='module')
def ffa(t3_make_tourney):
    return t3_make_tourney(
        StageType.ffa_simple,
        4,
        mode=TournamentMode.ffa,
        settings={
            'max_players_per_match': 8,
            'placement_points_rules': PLACEMENT_POINTS_RULES,
        },
    )


@pytest.mark.parametrize(
    ('placements', 'kills', 'message'),
    [
        (['', '2', '3', '4'], ['1'] * 4, 'Bitte für jeden belegten Slot einen Ingame-Platz eintragen.'),
        (['1', 'two', '3', '4'], ['1'] * 4, 'Ingame-Plätze müssen als ganze Zahl eingetragen werden.'),
        (['1', '2', '3', '1000'], ['1'] * 4, 'Ingame-Plätze müssen zwischen 1 und 999 liegen.'),
        (['1', '2', '3', '4'], ['1', '', '1', '1'], 'Bitte für jeden belegten Slot eine Kill-Zahl eintragen.'),
        (['1', '2', '3', '4'], ['1', 'many', '1', '1'], 'Kills müssen als ganze Zahl eingetragen werden.'),
        (['1', '2', '3', '4'], ['1', '1', '-1', '1'], 'Kills müssen zwischen 0 und 999 liegen.'),
        (['1', '2', '2', '4'], ['1'] * 4, 'Jeder belegte Slot braucht einen eindeutigen Ingame-Platz.'),
        (['2', '3', '4', '5'], ['1'] * 4, 'Genau ein belegter Slot muss den Ingame-Platz 1 erhalten.'),
    ],
)  # fmt: skip
def test_invalid_ffa_result_is_rejected(
    t3_client, t3_assert_flash, ffa, placements, kills, message
):
    (match,) = ffa.matches()
    data = _ffa_data(ffa.slots(match), placements, kills)

    _post(t3_client, ffa.url + f'/matches/{match.id}/result', data)

    t3_assert_flash(t3_client, 'danger', message)
    assert _result(match) is None


def test_ffa_result_gets_placement_points(t3_client, t3_assert_flash, ffa):
    (match,) = ffa.matches()
    slots = ffa.slots(match)
    data = _ffa_data(slots, ['3', '1', '4', '2'], ['0', '7', '1', '2'])

    response = _post(
        t3_client,
        ffa.url + f'/matches/{match.id}/result',
        {**data, 'idempotency_key': 't3-ffa-result', 'comment': ' GG '},
    )

    assert response.location.endswith('?tab=matches')
    t3_assert_flash(t3_client, 'success', 'Ergebnis wurde gespeichert.')
    result = _result(match)
    assert result.winner_slot == slots[1].slot_no
    nos = [str(slot.slot_no) for slot in slots]
    assert result.score['metric'] == 'kills'
    assert result.score['slots'] == dict(zip(nos, [0, 7, 1, 2], strict=True))
    assert result.ranking['metric'] == 'placement_points'
    assert result.ranking['placements'] == dict(
        zip(nos, [3, 1, 4, 2], strict=True)
    )
    assert result.ranking['points'] == dict(
        zip(nos, [5, 10, 0, 5], strict=True)
    )
    assert ffa.match(match.id).state == MatchState.completed


def test_ffa_result_needs_two_players(
    t3_client, t3_assert_flash, t3_make_tourney
):
    tourney = t3_make_tourney(
        StageType.ffa_simple,
        2,
        mode=TournamentMode.ffa,
        settings={'max_players_per_match': 8},
        publish=False,
    )
    (match,) = tourney.matches()
    _post(t3_client, tourney.url + f'/matches/{match.id}/slots/2', {})
    t3_assert_flash(t3_client, 'success', 'Match-Slot wurde aktualisiert.')

    _post(
        t3_client,
        tourney.url + f'/matches/{match.id}/result',
        {'placement_slot_1': '1', 'kills_slot_1': '0'},
    )

    t3_assert_flash(
        t3_client,
        'danger',
        'Ein FFA-Match braucht mindestens zwei belegte Slots, bevor ein '
        'Ergebnis gespeichert werden kann.',
    )


def _occupied(tourney, match):
    return [slot for slot in tourney.slots(match) if slot.participant_id]


def _flatout2_generation_data(participants):
    track = FLATOUT2_TRACK_CHOICES_BY_MODE['single_race'][0]
    vehicle = FLATOUT2_VEHICLE_CHOICES_BY_MODE['single_race'][0]
    data = {
        'round_starts_at_round_1': '',
        'flatout2_match_count_round_1': '1',
        'flatout2_race_count_round_1': '1',
        'flatout2_mode_round_1_race_1': 'single_race',
        'flatout2_track_round_1_race_1': track,
        'flatout2_vehicle_round_1_race_1': vehicle,
    }
    for slot_no, participant in enumerate(participants, start=1):
        key = f'flatout2_participant_round_1_match_1_slot_{slot_no}'
        data[key] = str(participant.id)
    return data


@pytest.fixture(scope='module')
def flatout2(t3_make_tourney, t3_client, t3_flashes):
    tourney = t3_make_tourney(
        StageType.ffa_flatout2_single_elimination,
        3,
        mode=TournamentMode.ffa,
        settings={'max_players_per_match': 8},
        generate=False,
    )
    response = t3_client.post(
        tourney.url + f'/stages/{tourney.stage.id}/generate',
        data=_flatout2_generation_data(tourney.participants()),
    )
    assert response.status_code == 302, t3_flashes(t3_client)
    t3_flashes(t3_client)
    assert len(tourney.matches()) == 1
    return tourney


def test_flatout2_match_view_and_host(t3_client, t3_assert_flash, flatout2):
    (match,) = flatout2.matches()
    url = flatout2.url + f'/matches/{match.id}'
    host = flatout2.participant_of(flatout2.players[1])

    body = t3_client.get(url).get_data(as_text=True)
    assert 'FlatOut 2 Setup' in body
    assert FLATOUT2_TRACK_CHOICES_BY_MODE['single_race'][0] in body
    assert 'Host speichern' in body

    response = _post(
        t3_client,
        url + '/host',
        {'host_participant_id': str(host.id), 'return_to': 'match'},
    )
    assert response.location.endswith(f'/matches/{match.id}')
    t3_assert_flash(t3_client, 'success', 'FlatOut-2-Host wurde aktualisiert.')
    settings = flatout2.match(match.id).settings
    assert settings['host_participant_id'] == str(host.id)

    body = t3_client.get(url).get_data(as_text=True)
    assert f'<option value="{host.id}" selected>' in body

    _post(t3_client, url + '/host', {'host_participant_id': ''})
    t3_assert_flash(t3_client, 'success', 'FlatOut-2-Host wurde aktualisiert.')
    assert not flatout2.match(match.id).settings.get('host_participant_id')


def test_flatout2_host_must_play_in_the_match(
    t3_client, t3_assert_flash, flatout2, ffa
):
    (match,) = flatout2.matches()
    stranger = ffa.participant_of(ffa.players[0])

    _post(
        t3_client,
        flatout2.url + f'/matches/{match.id}/host',
        {'host_participant_id': str(stranger.id)},
    )

    t3_assert_flash(
        t3_client, 'danger', 'Der gewählte Host spielt nicht in diesem Match.'
    )


@pytest.mark.parametrize(
    ('points', 'message'),
    [
        (['10', '', '5'], 'Bitte für jeden belegten Slot Punkte eintragen.'),
        (
            ['10', 'lots', '5'],
            'Punkte müssen als ganze Zahl eingetragen werden.',
        ),
        (['10', '10000', '5'], 'Punkte müssen zwischen 0 und 9999 liegen.'),
        (['12', '12', '5'], 'Der höchste Punktestand muss eindeutig sein.'),
    ],
)
def test_invalid_flatout2_result_is_rejected(
    t3_client, t3_assert_flash, flatout2, points, message
):
    (match,) = flatout2.matches()
    data = {
        f'points_slot_{slot.slot_no}': value
        for slot, value in zip(_occupied(flatout2, match), points, strict=True)
    }

    _post(t3_client, flatout2.url + f'/matches/{match.id}/result', data)

    t3_assert_flash(t3_client, 'danger', message)
    assert _result(match) is None


def test_flatout2_result_is_ranked_by_points(
    t3_client, t3_assert_flash, flatout2
):
    (match,) = flatout2.matches()
    slots = _occupied(flatout2, match)
    data = {
        f'points_slot_{slot.slot_no}': value
        for slot, value in zip(slots, ['20', '35', '20'], strict=True)
    }

    _post(t3_client, flatout2.url + f'/matches/{match.id}/result', data)

    t3_assert_flash(t3_client, 'success', 'Ergebnis wurde gespeichert.')
    result = _result(match)
    nos = [str(slot.slot_no) for slot in slots]
    assert result.winner_slot == slots[1].slot_no
    assert result.score['metric'] == 'points'
    assert result.ranking['placements'] == dict(
        zip(nos, [2, 1, 3], strict=True)
    )
    assert result.ranking['points'] == dict(zip(nos, [20, 35, 20], strict=True))
