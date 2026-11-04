"""
byceps.services.netsession_tourney.blueprints.admin.route_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext


CREATE_WIZARD_SESSION_KEY = 'netsession_tourney_create_wizard'
STAGE_BUILDER_WIZARD_SESSION_KEY = 'netsession_tourney_stage_builder_wizard'
TOURNAMENT_DETAIL_TABS = {
    'overview',
    'stages',
    'participants',
    'matches',
    'prizes',
    'discord',
    'notifications',
}
DISCORD_DM_EVENT_CHOICES = [
    ('tournament_live', gettext('Turnier live')),
    ('tournament_canceled', gettext('Turnier abgesagt')),
    ('match_ready', gettext('Match spielbereit')),
    ('flatout2_host_assigned', gettext('FlatOut 2 Host ausgewählt')),
    ('result_submitted', gettext('Ergebnis übermittelt')),
]
DISCORD_FORUM_EVENT_CHOICES = [
    ('manual_announcement', gettext('Manuelle Turniermeldung')),
    ('match_completed', gettext('Match beendet')),
    ('stage_started', gettext('Stage gestartet')),
    ('tournament_canceled', gettext('Turnier abgesagt')),
    ('tournament_finished', gettext('Turnier beendet')),
    ('tournament_live', gettext('Turnier live')),
]
