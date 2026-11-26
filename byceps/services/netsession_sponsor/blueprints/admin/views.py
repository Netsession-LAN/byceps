"""
byceps.services.netsession_sponsor.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sponsors of a party: list, create, update, delete, reorder.
"""

from __future__ import annotations

from flask import abort, request
from flask_babel import gettext

from byceps.services.netsession_sponsor import logo_storage, sponsor_service
from byceps.services.party import party_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .forms import CreateForm, UpdateForm


blueprint = create_blueprint('netsession_sponsor_admin', __name__)


@blueprint.get('/for_party/<party_id>')
@permission_required('ns_sponsor.view')
@templated
def index(party_id):
    party = _get_party_or_404(party_id)
    sponsors = sponsor_service.get_sponsors_for_party(party.id)
    return {'party': party, 'sponsors': sponsors}


@blueprint.get('/for_party/<party_id>/create')
@permission_required('ns_sponsor.update')
@templated
def create_form(party_id, erroneous_form=None):
    party = _get_party_or_404(party_id)
    form = erroneous_form if erroneous_form else CreateForm()
    return {'party': party, 'form': form}


@blueprint.post('/for_party/<party_id>')
@permission_required('ns_sponsor.update')
def create(party_id):
    party = _get_party_or_404(party_id)
    form = CreateForm(_form_fields())
    if not form.validate():
        return create_form(party.id, form)

    logo_path = _store(party.id, 'logo')
    logo_dark_path = _store(party.id, 'logo_dark')
    if not logo_path or logo_dark_path is False:
        return create_form(party.id, form)

    sponsor = sponsor_service.create_sponsor(
        party.id,
        form.name.data,
        logo_path,
        logo_dark_path=logo_dark_path or None,
        target_url=form.target_url.data,
        enabled=form.enabled.data,
    )
    flash_success(gettext('Sponsor "%(name)s" angelegt.', name=sponsor.name))
    return redirect_to('.index', party_id=party.id)


@blueprint.get('/sponsors/<uuid:sponsor_id>/update')
@permission_required('ns_sponsor.update')
@templated
def update_form(sponsor_id, erroneous_form=None):
    sponsor = _get_sponsor_or_404(sponsor_id)
    party = party_service.get_party(sponsor.party_id)
    form = erroneous_form if erroneous_form else UpdateForm(obj=sponsor)
    return {'party': party, 'sponsor': sponsor, 'form': form}


@blueprint.post('/sponsors/<uuid:sponsor_id>')
@permission_required('ns_sponsor.update')
def update(sponsor_id):
    sponsor = _get_sponsor_or_404(sponsor_id)
    form = UpdateForm(_form_fields())
    if not form.validate():
        return update_form(sponsor.id, form)

    logo_path = _store(sponsor.party_id, 'logo')
    logo_dark_path = _store(sponsor.party_id, 'logo_dark')
    if logo_path is False or logo_dark_path is False:
        return update_form(sponsor.id, form)

    sponsor_service.update_sponsor(
        sponsor.id,
        form.name.data,
        target_url=form.target_url.data,
        enabled=form.enabled.data,
        logo_path=logo_path or None,
        logo_dark_path=logo_dark_path or None,
        remove_logo_dark=form.remove_logo_dark.data,
    ).unwrap()
    flash_success(
        gettext('Sponsor "%(name)s" gespeichert.', name=form.name.data)
    )
    return redirect_to('.index', party_id=sponsor.party_id)


@blueprint.post('/sponsors/<uuid:sponsor_id>/delete')
@permission_required('ns_sponsor.update')
def delete(sponsor_id):
    sponsor = _get_sponsor_or_404(sponsor_id)
    sponsor_service.delete_sponsor(sponsor.id)
    flash_success(gettext('Sponsor "%(name)s" gelöscht.', name=sponsor.name))
    return redirect_to('.index', party_id=sponsor.party_id)


@blueprint.post('/sponsors/<uuid:sponsor_id>/up')
@permission_required('ns_sponsor.update')
def move_up(sponsor_id):
    return _move(sponsor_id, -1)


@blueprint.post('/sponsors/<uuid:sponsor_id>/down')
@permission_required('ns_sponsor.update')
def move_down(sponsor_id):
    return _move(sponsor_id, 1)


def _move(sponsor_id, offset: int):
    sponsor = _get_sponsor_or_404(sponsor_id)
    match sponsor_service.move_sponsor(sponsor.id, offset):
        case Err(error):
            flash_error(error)
    return redirect_to('.index', party_id=sponsor.party_id)


def _form_fields():
    """Make `InputRequired` work on `FileField`."""
    fields = request.form.copy()
    fields.update({k: v for k, v in request.files.items() if v.filename})
    return fields


def _store(party_id, field_name: str):
    """Path of the stored upload, '' if none was sent, False on error."""
    upload = request.files.get(field_name)
    if upload is None or not upload.filename:
        return ''
    match logo_storage.store_logo(party_id, upload.stream):
        case Ok(path):
            return path
        case Err(error):
            flash_error(error)
            return False


def _get_party_or_404(party_id):
    party = party_service.find_party(party_id)
    if party is None:
        abort(404)
    return party


def _get_sponsor_or_404(sponsor_id):
    sponsor = sponsor_service.find_sponsor(sponsor_id)
    if sponsor is None:
        abort(404)
    return sponsor
