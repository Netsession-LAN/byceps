"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_forum_images
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the Discord forum image library (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    ManagedLogoLabelForm,
    ManagedLogoUploadForm,
)
from byceps.services.netsession_tourney.logo_service import (
    delete_discord_forum_image_asset,
    get_discord_forum_image_assets,
    set_discord_forum_image_label,
    upload_discord_forum_image,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
)

from .result_helpers import get_party_or_404
from .wizard_lookups import (
    get_discord_forum_image_asset_or_404,
)


def register_discord_forum_image_upload_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/logos/discord-forum')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/logo/discord_forum_index')
    def discord_forum_image_index(party_id, erroneous_upload_form=None):
        party = get_party_or_404(party_id)
        upload_form = (
            erroneous_upload_form
            if erroneous_upload_form is not None
            else ManagedLogoUploadForm()
        )
        return {
            'party': party,
            'logo_assets': get_discord_forum_image_assets(party.id),
            'upload_form': upload_form,
            'current_logo_subtab': 'discord_forum',
        }

    @blueprint.post('/for_party/<party_id>/logos/discord-forum/upload')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_upload(party_id):
        party = get_party_or_404(party_id)
        form_data = request.form.copy()
        if request.files:
            form_data.update(request.files)
        form = ManagedLogoUploadForm(form_data)
        if not form.validate() or form.file.data is None:
            flash_error(gettext('Bitte eine Datei auswählen.'))
            return discord_forum_image_index(party.id, form)

        match upload_discord_forum_image(
            party.id,
            g.user.as_user(),
            form.file.data.stream,
            label=form.label.data,
            original_filename=form.file.data.filename,
        ):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde hochgeladen.'))
            case Err(message):
                flash_error(message)
                return discord_forum_image_index(party.id, form)

        return redirect_to('.discord_forum_image_index', party_id=party.id)


def register_discord_forum_image_edit_routes(blueprint):
    @blueprint.get('/logos/discord-forum/<uuid:image_asset_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/logo/discord_forum_update_form')
    def discord_forum_image_update_form(image_asset_id, erroneous_form=None):
        image_asset = get_discord_forum_image_asset_or_404(image_asset_id)
        party = get_party_or_404(image_asset.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else ManagedLogoLabelForm(data={'label': image_asset.label})
        )
        return {
            'party': party,
            'logo_asset': image_asset,
            'form': form,
            'current_logo_subtab': 'discord_forum',
        }

    @blueprint.post('/logos/discord-forum/<uuid:image_asset_id>')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_update(image_asset_id):
        image_asset = get_discord_forum_image_asset_or_404(image_asset_id)
        party = get_party_or_404(image_asset.party_id)
        form = ManagedLogoLabelForm(request.form)
        if not form.validate():
            return discord_forum_image_update_form(image_asset.id, form)

        match set_discord_forum_image_label(
            image_asset.id, g.user.as_user(), form.label.data
        ):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde umbenannt.'))
            case Err(message):
                flash_error(message)
                return discord_forum_image_update_form(image_asset.id, form)

        return redirect_to('.discord_forum_image_index', party_id=party.id)

    @blueprint.post('/logos/discord-forum/<uuid:image_asset_id>/delete')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_delete(image_asset_id):
        image_asset = get_discord_forum_image_asset_or_404(image_asset_id)
        party = get_party_or_404(image_asset.party_id)

        match delete_discord_forum_image_asset(image_asset.id):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to('.discord_forum_image_index', party_id=party.id)
