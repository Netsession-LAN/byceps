"""Admin match handling of duels: results, walkover, result deletion,
rescheduling, disputes, slots and host."""

from datetime import datetime
from uuid import uuid4

import pytest

from byceps.database import db
from byceps.services.netsession_tourney import double_grand_final
from byceps.services.netsession_tourney.models import MatchState


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]


def _post(client, url, data=None):
    response = client.post(url, data=data or {})
    assert response.status_code == 302
    return response


def _result(match):
    db.session.expire_all()
    return double_grand_final.get_match_results({match.id}).get(match.id)


@pytest.fixture(scope='module')
def live(t3_make_tourney):
    """Four players, two open first-round matches, final pending."""
    return t3_make_tourney(count=4)


def test_report_result_and_return_to_match(t3_client, t3_assert_flash, live):
    match = live.open_matches()[0]
    match_url = live.url + f'/matches/{match.id}'

    response = _post(
        t3_client,
        match_url + '/result',
        {
            'slot_1_points': '2',
            'slot_2_points': '5',
            'comment': '  ',
            'return_to': 'match',
            'parent_return_to': 'stages',
            'parent_stage_id': str(live.stage.id),
        },
    )

    assert response.location.endswith(
        f'{match_url}?return_to=stages&stage_id={live.stage.id}'.removeprefix(
            'http://admin.acmecon.test'
        )
    )
    t3_assert_flash(t3_client, 'success', 'Ergebnis wurde gespeichert.')
    assert live.match(match.id).state == MatchState.completed
    result = _result(match)
    assert result.winner_slot == 2
    assert result.score == {'display': '2:5'}

    # A correction needs a comment.
    _post(
        t3_client,
        match_url + '/result',
        {'slot_1_points': '5', 'slot_2_points': '2'},
    )
    t3_assert_flash(
        t3_client,
        'danger',
        'Korrekturen durch Admins brauchen einen Kommentar.',
    )
    assert _result(match).winner_slot == 2


@pytest.mark.parametrize(
    ('data', 'message'),
    [
        (
            {'slot_1_points': '3', 'slot_2_points': '3'},
            'Gleichstände sind bei der manuellen Ergebniserfassung nicht '
            'erlaubt.',
        ),
        ({'slot_1_points': '3'}, 'Ungültige Ergebnisdaten.'),
        (
            {'slot_1_points': '3', 'slot_2_points': '1000'},
            'Ungültige Ergebnisdaten.',
        ),
    ],
)
def test_invalid_result_is_rejected(
    t3_client, t3_assert_flash, live, data, message
):
    match = live.matches()[-1]

    response = _post(
        t3_client,
        live.url + f'/matches/{match.id}/result',
        {**data, 'return_to': 'match', 'parent_return_to': 'matches'},
    )

    assert response.location.endswith(f'/matches/{match.id}?return_to=matches')
    t3_assert_flash(t3_client, 'danger', message)
    assert _result(match) is None


def test_result_for_unknown_or_unready_match(t3_client, t3_flashes, live):
    response = _post(
        t3_client,
        live.url + f'/matches/{uuid4()}/result',
        {'slot_1_points': '1', 'slot_2_points': '0'},
    )
    assert response.location.endswith('?tab=matches')
    assert t3_flashes(t3_client) == [('danger', 'Unbekanntes Match.')]

    final = live.matches()[-1]
    assert final.state == MatchState.pending
    _post(
        t3_client,
        live.url + f'/matches/{final.id}/result',
        {
            'slot_1_points': '1',
            'slot_2_points': '0',
            'return_to': 'match',
            'parent_return_to': 'stages',
            'parent_stage_id': 'not-a-uuid',
        },
    )
    (flash,) = t3_flashes(t3_client)
    assert flash[0] == 'danger'
    assert _result(final) is None


def test_walkover(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=2)
    (match,) = tourney.matches()
    url = tourney.url + f'/matches/{match.id}/walkover'

    _post(t3_client, url, {'winner_slot': '1'})
    t3_assert_flash(
        t3_client, 'danger', 'Ungültige Daten für den kampflosen Sieg.'
    )

    _post(t3_client, url, {'winner_slot': '1', 'comment': 'No show'})
    t3_assert_flash(t3_client, 'success', 'Kampfloser Sieg wurde gespeichert.')
    result = _result(match)
    assert result.winner_slot == 1
    assert result.score == {'walkover': True}

    _post(t3_client, url, {'winner_slot': '2', 'comment': 'Again'})
    t3_assert_flash(
        t3_client,
        'danger',
        'Das Match hat schon ein Ergebnis. Zum Ändern das Ergebnis '
        'korrigieren.',
    )


def test_delete_result(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=2)
    (match,) = tourney.matches()
    url = tourney.url + f'/matches/{match.id}'

    _post(t3_client, url + '/result/delete')
    t3_assert_flash(
        t3_client, 'danger', 'Für dieses Match ist kein Ergebnis gespeichert.'
    )

    _post(
        t3_client, url + '/result', {'slot_1_points': '1', 'slot_2_points': '0'}
    )
    t3_assert_flash(t3_client, 'success', 'Ergebnis wurde gespeichert.')

    response = _post(t3_client, url + '/result/delete', {'return_to': 'match'})
    assert response.location.endswith(f'/matches/{match.id}')
    t3_assert_flash(t3_client, 'success', 'Ergebnis wurde gelöscht.')
    assert _result(match) is None
    assert tourney.match(match.id).state != MatchState.completed


def test_reschedule(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=2)
    (match,) = tourney.matches()
    url = tourney.url + f'/matches/{match.id}'

    _post(t3_client, url + '/reschedule', {'scheduled_at': 'tomorrow'})
    t3_assert_flash(t3_client, 'danger', 'Ungültige Planungsdaten.')

    _post(
        t3_client,
        url + '/reschedule',
        {'scheduled_at': '2026-12-05T20:15', 'comment': 'Server down'},
    )
    t3_assert_flash(t3_client, 'success', 'Match wurde neu angesetzt.')
    # entered in the user's time zone (Europe/Berlin), stored in UTC
    assert tourney.match(match.id).scheduled_at == datetime(2026, 12, 5, 19, 15)

    _post(
        t3_client,
        url + '/walkover',
        {'winner_slot': '2', 'comment': 'No show'},
    )
    t3_assert_flash(t3_client, 'success', 'Kampfloser Sieg wurde gespeichert.')
    _post(
        t3_client,
        url + '/reschedule',
        {'scheduled_at': '2026-12-05T21:00', 'comment': 'Too late'},
    )
    t3_assert_flash(
        t3_client,
        'danger',
        'Abgeschlossene Matches lassen sich nicht neu ansetzen.',
    )


def test_dispute(t3_client, t3_assert_flash, live):
    match = live.open_matches()[-1]
    url = live.url + f'/matches/{match.id}/dispute'

    _post(t3_client, url, {'reason_code': 'score_conflict'})
    t3_assert_flash(t3_client, 'danger', 'Ungültige Streitfall-Daten.')

    _post(t3_client, url, {'reason_code': 'score_conflict', 'comment': 'Lag'})
    t3_assert_flash(t3_client, 'success', 'Streitfall wurde eröffnet.')
    assert live.match(match.id).state == MatchState.disputed

    final = live.matches()[-1]
    _post(
        t3_client,
        live.url + f'/matches/{final.id}/dispute',
        {'reason_code': 'score_conflict', 'comment': 'Too early'},
    )
    t3_assert_flash(
        t3_client,
        'danger',
        'Ein Streitfall ist nur bei offenen Matches möglich. Ein '
        'abgeschlossenes Ergebnis lässt sich korrigieren.',
    )


def test_set_slots_in_draft(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=4, publish=False)
    first, second = tourney.matches()[:2]
    first_slot = tourney.slots(first)[0]
    second_slot = tourney.slots(second)[0]
    url = tourney.url + f'/matches/{first.id}/slots/{first_slot.slot_no}'

    _post(t3_client, url, {'participant_id': 'nobody'})
    t3_assert_flash(t3_client, 'danger', 'Ungültiger Teilnehmer.')

    moved = {'participant_id': str(second_slot.participant_id)}
    _post(t3_client, url, moved)
    t3_assert_flash(
        t3_client,
        'danger',
        'Der Teilnehmer ist in dieser Runde bereits zugewiesen.',
    )

    second_url = (
        tourney.url + f'/matches/{second.id}/slots/{second_slot.slot_no}'
    )
    _post(t3_client, second_url, {'participant_id': '', 'comment': 'Free'})
    t3_assert_flash(t3_client, 'success', 'Match-Slot wurde aktualisiert.')
    _post(t3_client, url, {**moved, 'comment': 'Swap'})
    t3_assert_flash(t3_client, 'success', 'Match-Slot wurde aktualisiert.')
    assert tourney.slots(second)[0].participant_id is None
    assert tourney.slots(first)[0].participant_id == second_slot.participant_id

    _post(t3_client, url, {'participant_id': str(uuid4())})
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Teilnehmer.')

    _post(t3_client, tourney.url + f'/matches/{first.id}/slots/9', {})
    t3_assert_flash(t3_client, 'danger', 'Unbekannter Platz im Match.')


def test_slots_are_locked_once_live(t3_client, t3_assert_flash, live):
    match = live.matches()[0]

    _post(t3_client, live.url + f'/matches/{match.id}/slots/1', {})

    t3_assert_flash(
        t3_client, 'danger', 'Matches lassen sich nur im Entwurf zuweisen.'
    )


def test_host_only_for_flatout2(t3_client, t3_assert_flash, live):
    url = live.url + f'/matches/{live.matches()[0].id}/host'

    _post(t3_client, url, {'host_participant_id': 'host'})
    t3_assert_flash(t3_client, 'danger', 'Ungültiger Host.')

    _post(t3_client, url, {'host_participant_id': ''})
    t3_assert_flash(
        t3_client, 'danger', 'Dieses Match gehört zu keiner FlatOut-2-Phase.'
    )


@pytest.mark.parametrize(
    'action',
    [
        'result',
        'walkover',
        'result/delete',
        'reschedule',
        'dispute',
        'slots/1',
        'host',
    ],
)
def test_unknown_tournament_is_not_found(t3_client, live, action):
    url = (
        'http://admin.acmecon.test/ns-tourneys'
        f'/for_party/{live.party.id}/tournaments/{uuid4()}'
        f'/matches/{uuid4()}/{action}'
    )

    assert t3_client.post(url, data={}).status_code == 404
