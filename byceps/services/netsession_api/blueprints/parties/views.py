"""
byceps.services.netsession_api.blueprints.parties.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Party list for read-only clients (Screens), at `/v1/ns-parties`.
Needs `ns_api.read`.
"""

from datetime import datetime, UTC

from flask import request

from byceps.services.party import party_service
from byceps.services.site import site_service
from byceps.services.site.models import SiteID
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified

from ...token_auth import read_token_required


CURRENT_PARTY_SITE_ID = 'netsession'


blueprint = create_blueprint('netsession_parties_api', __name__)


@blueprint.after_request
def add_etag(response):
    if request.method == 'GET' and response.status_code == 200:
        response.add_etag(weak=True)
        response = response.make_conditional(request)
    return response


@blueprint.get('')
@read_token_required
@jsonified
def parties():
    """All parties, newest first; `is_current` marks the current party of
    site `netsession` (what the website shows)."""
    brand_id = request.args.get('brand_id')
    site = site_service.find_site(SiteID(CURRENT_PARTY_SITE_ID))
    current_party_id = site.party_id if site is not None else None
    all_parties = sorted(
        party_service.get_all_parties(),
        key=lambda party: party.starts_at,
        reverse=True,
    )
    return [
        {
            'id': party.id,
            'title': party.title,
            'brand_id': party.brand_id,
            'starts_at': _iso(party.starts_at),
            'ends_at': _iso(party.ends_at),
            'is_current': party.id == current_party_id,
            'archived': party.archived,
            'canceled': party.canceled,
            'hidden': party.hidden,
        }
        for party in all_parties
        if brand_id is None or party.brand_id == brand_id
    ]


def _iso(value: datetime) -> str:
    """Stored as naive UTC; output with offset."""
    return value.replace(tzinfo=UTC).isoformat()
