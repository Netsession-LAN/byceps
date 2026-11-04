"""
byceps.services.netsession_tourney.signals.events
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from blinker import Namespace


netsession_tourney_signals = Namespace()


tournament_published = netsession_tourney_signals.signal('tournament-published')
stage_started = netsession_tourney_signals.signal('stage-started')
match_ready = netsession_tourney_signals.signal('match-ready')
result_submitted = netsession_tourney_signals.signal('result-submitted')
