"""
byceps.services.netsession_tourney.blueprints.api.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from time import perf_counter

from flask import abort, g, request

from byceps.services.party import party_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified

from ...models import TournamentMode, TournamentStatus
from ...observability_service import record_api_request_metric
from ...match_queries import get_matches_for_tournament
from ...tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from ...tournament_service import (
    find_tournament_for_party,
    get_tournaments_for_party,
)


blueprint = create_blueprint('netsession_tourney_api', __name__)


@blueprint.before_request
def before_request():
    g.ns_tourney_api_request_started = perf_counter()


@blueprint.after_request
def after_request(response):
    started = getattr(g, 'ns_tourney_api_request_started', None)
    if started is None or 400 <= response.status_code < 500:
        # The API is public: a row per bad request would let anybody fill
        # the metrics table.
        return response

    duration_ms = int((perf_counter() - started) * 1000)
    party_id = request.args.get('party_id')
    endpoint = request.endpoint or request.path

    record_api_request_metric(
        endpoint=endpoint,
        method=request.method,
        status_code=response.status_code,
        duration_ms=duration_ms,
        party_id=party_id,
    )

    return response


@blueprint.get('/tournaments')
@jsonified
def get_tournaments():
    party_id = request.args.get('party_id')
    if not party_id:
        abort(400)
    if party_service.find_party(party_id) is None:
        abort(404)

    status = request.args.get('status')
    mode = request.args.get('mode')

    status_obj = _parse_status(status)
    mode_obj = _parse_mode(mode)

    tournaments = get_tournaments_for_party(
        party_id,
        status=status_obj,
        mode=mode_obj,
        game=request.args.get('game'),
        visible_on_site=True,
    )
    return [serialize_tournament(tournament) for tournament in tournaments]


@blueprint.get('/tournaments/<uuid:tournament_id>')
@jsonified
def get_tournament(tournament_id):
    party_id = request.args.get('party_id')
    if not party_id:
        abort(400)
    if party_service.find_party(party_id) is None:
        abort(404)

    tournament = find_tournament_for_party(
        party_id, tournament_id, visible_on_site=True
    )
    if tournament is None:
        abort(404)

    stages = get_stages_for_tournament(party_id, tournament.id)
    participants = get_participants_for_tournament(party_id, tournament.id)
    matches = get_matches_for_tournament(party_id, tournament.id)

    return {
        'tournament': serialize_tournament(tournament),
        'stages': [serialize_stage(stage) for stage in stages],
        'participants': [
            serialize_participant(participant) for participant in participants
        ],
        'matches': [serialize_match(match) for match in matches],
    }


def serialize_tournament(tournament):
    return {
        'id': str(tournament.id),
        'party_id': tournament.party_id,
        'category_id': str(tournament.category_id),
        'slug': tournament.slug,
        'title': tournament.title,
        'subtitle': tournament.subtitle,
        'game': tournament.game,
        'mode': tournament.mode.value,
        'status': tournament.status.value,
        'starts_at': tournament.starts_at and tournament.starts_at.isoformat(),
        'registration_open': tournament.registration_open,
    }


def serialize_stage(stage):
    return {
        'id': str(stage.id),
        'order_no': stage.order_no,
        'type': stage.type.value,
        'name': stage.name,
        'status': stage.status.value,
        'settings': stage.settings,
    }


def serialize_participant(participant):
    return {
        'id': str(participant.id),
        'name': participant.name,
        'type': participant.type.value,
        'logo_url': participant.logo_url,
        'seed': participant.seed,
        'status': participant.status.value,
        'checkin_state': participant.checkin_state.value,
    }


def serialize_match(match):
    return {
        'id': str(match.id),
        'stage_id': str(match.stage_id),
        'round_no': match.round_no,
        'match_no': match.match_no,
        'state': match.state.value,
        'scheduled_at': match.scheduled_at and match.scheduled_at.isoformat(),
    }


def _parse_status(value):
    if not value:
        return None
    try:
        return TournamentStatus(value)
    except ValueError:
        return None


def _parse_mode(value):
    if not value:
        return None
    try:
        return TournamentMode(value)
    except ValueError:
        return None
