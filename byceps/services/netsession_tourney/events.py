"""
byceps.services.netsession_tourney.events
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass

from byceps.services.core.events import BaseEvent
from byceps.services.user.models import UserID

from .models import MatchID, StageID, TournamentID


@dataclass(frozen=True, kw_only=True)
class NetsessionTourneyEvent(BaseEvent):
    tournament_id: TournamentID


@dataclass(frozen=True, kw_only=True)
class NetsessionTourneyPublishedEvent(NetsessionTourneyEvent):
    actor_user_id: UserID


@dataclass(frozen=True, kw_only=True)
class NetsessionTourneyStageStartedEvent(NetsessionTourneyEvent):
    stage_id: StageID


@dataclass(frozen=True, kw_only=True)
class NetsessionTourneyMatchReadyEvent(NetsessionTourneyEvent):
    stage_id: StageID
    match_id: MatchID


@dataclass(frozen=True, kw_only=True)
class NetsessionTourneyResultSubmittedEvent(NetsessionTourneyEvent):
    stage_id: StageID
    match_id: MatchID
    actor_user_id: UserID
