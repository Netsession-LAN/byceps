"""
byceps.services.netsession_newsletter.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from flask_babel import lazy_gettext

from byceps.util.authz import register_permissions


register_permissions(
    'ns_newsletter',
    [
        (
            'sync',
            lazy_gettext(
                'Newsletter-Abonnenten für den Sendy-Abgleich lesen und abmelden'
            ),
        ),
    ],
)
