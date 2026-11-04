"""
byceps.services.netsession_tourney.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from flask_babel import lazy_gettext

from byceps.util.authz import register_permissions


register_permissions(
    'netsession_tourney',
    [
        ('view', lazy_gettext('View Netsession tournaments')),
        (
            'participate',
            lazy_gettext('Participate in Netsession tournaments'),
        ),
        ('report_result', lazy_gettext('Netsession-Matchergebnisse melden')),
        ('manage', lazy_gettext('Manage Netsession tournaments')),
        ('admin', lazy_gettext('Administer Netsession tournaments')),
    ],
)
