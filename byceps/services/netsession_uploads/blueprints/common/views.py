"""
byceps.services.netsession_uploads.blueprints.common.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Readable answer to uploads above the size limit (site and admin): back to
the form with a message instead of the bare "413" page.
"""

from flask import redirect

from byceps.services.netsession_uploads.upload_limits import (
    build_too_large_message,
    find_same_host_referrer_path,
    get_max_upload_bytes,
)
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error


blueprint = create_blueprint('netsession_uploads', __name__)


@blueprint.app_errorhandler(413)
def request_entity_too_large(error):
    message = build_too_large_message()
    target = find_same_host_referrer_path()
    if target is None:
        return message, 413
    flash_error(message)
    return redirect(target)


@blueprint.app_template_global()
def ns_upload_max_bytes() -> int:
    return get_max_upload_bytes()


@blueprint.app_template_global()
def ns_upload_too_large_message() -> str:
    return build_too_large_message()
