"""
byceps.services.netsession_sponsor.blueprints.admin.forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from flask_babel import lazy_gettext
from wtforms import BooleanField, FileField, StringField
from wtforms.validators import InputRequired, Length, Optional, Regexp

from byceps.util.l10n import LocalizedForm


class _BaseForm(LocalizedForm):
    name = StringField(lazy_gettext('Name'), [InputRequired(), Length(max=80)])
    target_url = StringField(
        lazy_gettext('Link'),
        [
            Optional(),
            Length(max=500),
            Regexp(
                r'^https?://',
                message=lazy_gettext('Mit http:// oder https:// beginnen.'),
            ),
        ],
    )
    logo_dark = FileField(lazy_gettext('Logo für dunkle Bildschirme'))
    enabled = BooleanField(lazy_gettext('aktiv'), default=True)


class CreateForm(_BaseForm):
    logo = FileField(lazy_gettext('Logo'), [InputRequired()])


class UpdateForm(_BaseForm):
    logo = FileField(lazy_gettext('Logo'))
    remove_logo_dark = BooleanField(
        lazy_gettext('Logo für dunkle Bildschirme entfernen')
    )
