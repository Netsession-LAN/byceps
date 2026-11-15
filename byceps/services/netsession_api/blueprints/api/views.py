"""
byceps.services.netsession_api.blueprints.api.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Seat statistics for read-only clients (Screens), at `/v1/ns-seating`.
`ns-` prefix, so a future upstream API cannot collide. Needs `ns_api.read`.
"""

from flask import abort, request

from byceps.services.party import party_service
from byceps.services.seating import seat_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified

from ...token_auth import read_token_required


blueprint = create_blueprint('netsession_seating_api', __name__)


@blueprint.after_request
def add_etag(response):
    if request.method == 'GET' and response.status_code == 200:
        response.add_etag(weak=True)
        response = response.make_conditional(request)
    return response


@blueprint.get('/<party_id>/stats')
@read_token_required
@jsonified
def stats(party_id):
    if party_service.find_party(party_id) is None:
        abort(404)

    utilization = seat_service.get_seat_utilization(party_id)
    return {
        'seats_total': utilization.total,
        'seats_occupied': utilization.occupied,
    }
