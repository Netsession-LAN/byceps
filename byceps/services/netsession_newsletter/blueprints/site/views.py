"""
byceps.services.netsession_newsletter.blueprints.site.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unsubscribe page for the link in the newsletter mail, without login.
GET only asks (link scanners open links), POST unsubscribes.
"""

from __future__ import annotations

from datetime import datetime

from flask import render_template

from byceps.services.newsletter import newsletter_service
from byceps.services.user import user_service
from byceps.util.framework.blueprint import create_blueprint

from ... import unsubscribe_service, unsubscribe_token


blueprint = create_blueprint('netsession_newsletter', __name__)

_TEMPLATE = 'site/netsession_newsletter/unsubscribe.html'


@blueprint.get('/unsubscribe/<token>')
def unsubscribe_form(token):
    found = _find_user_and_list(token)
    if found is None:
        return render_template(_TEMPLATE, state='invalid'), 404
    _, list_ = found
    return render_template(
        _TEMPLATE, state='ask', token=token, list_title=list_.title
    )


@blueprint.post('/unsubscribe/<token>')
def unsubscribe(token):
    found = _find_user_and_list(token)
    if found is None:
        return render_template(_TEMPLATE, state='invalid'), 404
    user, list_ = found
    unsubscribe_service.unsubscribe(user, list_, datetime.utcnow())
    return render_template(
        _TEMPLATE, state='done', token=token, list_title=list_.title
    )


def _find_user_and_list(token: str):
    parsed = unsubscribe_token.parse(token)
    if parsed is None:
        return None
    user_id, list_id = parsed
    user = user_service.find_user(user_id)
    list_ = newsletter_service.find_list(list_id)
    if user is None or list_ is None:
        return None
    return user, list_
