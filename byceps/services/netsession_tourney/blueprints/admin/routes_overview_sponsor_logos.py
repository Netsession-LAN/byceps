"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_sponsor_logos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the sponsor logo library (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    SponsorLogoForm,
    SponsorLogoUploadForm,
)
from byceps.services.netsession_tourney.logo_service import (
    delete_sponsor_logo_asset,
    get_sponsor_logo_assets,
    set_sponsor_logo_label,
    upload_sponsor_logo_image,
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
    get_sponsor_logo_asset_or_404,
)


def register_sponsor_logo_upload_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/logos/sponsor')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/logo/sponsor_index')
    def sponsor_logo_index(party_id, erroneous_upload_form=None):
        party = get_party_or_404(party_id)
        upload_form = (
            erroneous_upload_form
            if erroneous_upload_form is not None
            else SponsorLogoUploadForm()
        )
        return {
            'party': party,
            'logo_assets': get_sponsor_logo_assets(party.id),
            'upload_form': upload_form,
            'current_logo_subtab': 'sponsor',
        }

    @blueprint.post('/for_party/<party_id>/logos/sponsor/upload')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_upload(party_id):
        party = get_party_or_404(party_id)
        form_data = request.form.copy()
        if request.files:
            form_data.update(request.files)
        form = SponsorLogoUploadForm(form_data)
        if not form.validate() or form.file.data is None:
            flash_error(gettext('Bitte eine Datei auswählen.'))
            return sponsor_logo_index(party.id, form)

        match upload_sponsor_logo_image(
            party.id,
            g.user.as_user(),
            form.file.data.stream,
            label=form.label.data,
            target_url=form.target_url.data,
            original_filename=form.file.data.filename,
        ):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde hochgeladen.'))
            case Err(message):
                flash_error(message)
                return sponsor_logo_index(party.id, form)

        return redirect_to('.sponsor_logo_index', party_id=party.id)


def register_sponsor_logo_edit_routes(blueprint):
    @blueprint.get('/logos/sponsor/<uuid:logo_asset_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/logo/sponsor_update_form')
    def sponsor_logo_update_form(logo_asset_id, erroneous_form=None):
        logo_asset = get_sponsor_logo_asset_or_404(logo_asset_id)
        party = get_party_or_404(logo_asset.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else SponsorLogoForm(
                data={
                    'label': logo_asset.label,
                    'target_url': logo_asset.target_url,
                }
            )
        )
        return {
            'party': party,
            'logo_asset': logo_asset,
            'form': form,
            'current_logo_subtab': 'sponsor',
        }

    @blueprint.post('/logos/sponsor/<uuid:logo_asset_id>')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_update(logo_asset_id):
        logo_asset = get_sponsor_logo_asset_or_404(logo_asset_id)
        party = get_party_or_404(logo_asset.party_id)
        form = SponsorLogoForm(request.form)
        if not form.validate():
            return sponsor_logo_update_form(logo_asset.id, form)

        match set_sponsor_logo_label(
            logo_asset.id,
            g.user.as_user(),
            form.label.data,
            target_url=form.target_url.data,
        ):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde umbenannt.'))
            case Err(message):
                flash_error(message)
                return sponsor_logo_update_form(logo_asset.id, form)

        return redirect_to('.sponsor_logo_index', party_id=party.id)

    @blueprint.post('/logos/sponsor/<uuid:logo_asset_id>/delete')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_delete(logo_asset_id):
        logo_asset = get_sponsor_logo_asset_or_404(logo_asset_id)
        party = get_party_or_404(logo_asset.party_id)

        match delete_sponsor_logo_asset(logo_asset.id):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to('.sponsor_logo_index', party_id=party.id)
