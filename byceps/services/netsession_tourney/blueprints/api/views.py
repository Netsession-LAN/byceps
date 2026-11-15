"""
byceps.services.netsession_tourney.blueprints.api.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All endpoints need an API token with `ns_api.read` (401/403 otherwise).
GET answers carry a weak ETag; `If-None-Match` gets 304.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from time import perf_counter

from flask import abort, g, request

from byceps.services.party import party_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified

from byceps.services.netsession_api.token_auth import read_token_required

from ...observability_service import record_api_request_metric
from ...tournament_prize_service import get_tournament_prizes_for_tournament
from ...tournament_service import (
    find_tournament_for_party,
    get_tournaments_for_party,
)
from ...filter_parsing import parse_tournament_status as _parse_status
from ...filter_parsing import parse_tournament_mode as _parse_mode
from ..site.tournament_ranking import compute_tournament_ranking
from .serializers import (
    serialize_match,
    serialize_participant,
    serialize_stage,
    serialize_standing,
    serialize_tournament,
)


blueprint = create_blueprint('netsession_tourney_api', __name__)


@blueprint.before_request
def before_request():
    g.ns_tourney_api_request_started = perf_counter()


@blueprint.after_request
def after_request(response):
    if request.method == 'GET' and response.status_code == 200:
        # Clients poll every few seconds: answer 304 if nothing changed.
        response.add_etag(weak=True)
        response = response.make_conditional(request)

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
@read_token_required
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
@read_token_required
@jsonified
def get_tournament(tournament_id):
    tournament = _get_tournament_or_404(tournament_id)
    ranking = compute_tournament_ranking(tournament.party_id, tournament.id)
    participants_by_id = {p.id: p for p in ranking.participants}
    slots_by_id = {
        slot.id: slot
        for slots in ranking.slots_by_match_id.values()
        for slot in slots
    }

    return {
        'tournament': serialize_tournament(tournament),
        'stages': [serialize_stage(stage) for stage in ranking.stages],
        'participants': [
            serialize_participant(p) for p in ranking.participants
        ],
        'matches': [
            serialize_match(
                match,
                ranking.slots_by_match_id.get(match.id, []),
                ranking.results_by_match_id.get(match.id),
                participants_by_id,
                slots_by_id,
            )
            for match in ranking.matches
        ],
    }


@blueprint.get('/tournaments/<uuid:tournament_id>/standings')
@read_token_required
@jsonified
def get_tournament_standings(tournament_id):
    """The ranking as on the site's ranking page, with prizes by rank."""
    tournament = _get_tournament_or_404(tournament_id)
    ranking = compute_tournament_ranking(tournament.party_id, tournament.id)
    prizes_by_position = {
        prize.position: prize
        for prize in get_tournament_prizes_for_tournament(tournament.id)
    }

    return {
        'tournament_id': str(tournament.id),
        'final': ranking.is_final,
        'has_results': ranking.has_data,
        'standings': [
            serialize_standing(row, prizes_by_position)
            for row in (ranking.rows if ranking.has_data else [])
        ],
    }


def _get_tournament_or_404(tournament_id):
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

    return tournament
