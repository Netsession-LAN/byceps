"""
byceps.services.netsession_api.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from flask_babel import lazy_gettext

from byceps.util.authz import register_permissions


register_permissions(
    'ns_api',
    [
        (
            'read',
            lazy_gettext(
                'Netsession-API lesen (Turniere, Sponsoren, Sitzplätze; z. B. für Screens)'
            ),
        ),
    ],
)
