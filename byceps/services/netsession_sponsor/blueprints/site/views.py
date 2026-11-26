"""
byceps.services.netsession_sponsor.blueprints.site.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No pages; provides `ns_sponsors()` to templates (homepage partner tile).
"""

from flask import g

from byceps.services.netsession_sponsor import sponsor_service
from byceps.services.netsession_sponsor.models import Sponsor
from byceps.util.framework.blueprint import create_blueprint


blueprint = create_blueprint('netsession_sponsor', __name__)


@blueprint.app_template_global()
def ns_sponsors() -> list[Sponsor]:
    """Active sponsors of the site's current party, in display order."""
    party = getattr(g, 'party', None)
    if party is None:
        return []
    return sponsor_service.get_sponsors_for_party(party.id, enabled_only=True)
