"""
byceps.services.netsession_sponsor.blueprints.api.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Active sponsors of a party for read-only clients (Screens). Needs an API
token with `ns_api.read`. Logo URLs are site paths (`/data/...`).
"""

from flask import abort, request

from byceps.services.netsession_api.token_auth import read_token_required
from byceps.services.netsession_sponsor import sponsor_service
from byceps.services.party import party_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified


blueprint = create_blueprint('netsession_sponsor_api', __name__)


@blueprint.after_request
def add_etag(response):
    if request.method == 'GET' and response.status_code == 200:
        response.add_etag(weak=True)
        response = response.make_conditional(request)
    return response


@blueprint.get('')
@read_token_required
@jsonified
def index():
    party_id = request.args.get('party_id')
    if not party_id:
        abort(400)
    if party_service.find_party(party_id) is None:
        abort(404)

    return [
        {
            'id': str(sponsor.id),
            'name': sponsor.name,
            'logo_url': sponsor.logo_url,
            'logo_url_dark': sponsor.logo_url_dark,
            'target_url': sponsor.target_url,
            'weight': sponsor.position,
        }
        for sponsor in sponsor_service.get_sponsors_for_party(
            party_id, enabled_only=True
        )
    ]
