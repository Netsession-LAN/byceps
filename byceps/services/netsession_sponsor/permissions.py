"""
byceps.services.netsession_sponsor.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from flask_babel import lazy_gettext

from byceps.util.authz import register_permissions


register_permissions(
    'ns_sponsor',
    [
        ('view', lazy_gettext('Sponsoren ansehen')),
        ('update', lazy_gettext('Sponsoren anlegen, ändern und löschen')),
    ],
)
