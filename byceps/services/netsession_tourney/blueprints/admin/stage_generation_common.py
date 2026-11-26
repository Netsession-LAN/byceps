"""
byceps.services.netsession_tourney.blueprints.admin.stage_generation_common
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared parts of the stage generation routes (see
`routes_stage_generation`): the request data, the generation block
check, redirects and flashing the generation result.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from flask_babel import gettext
from werkzeug.wrappers import Response

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers import (
    get_stage_generation_block_reason,
)
from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import Match, StageID
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result
from byceps.util.views import redirect_to


@dataclass(frozen=True, kw_only=True)
class StageGenerationRequest:
    party: Party
    tournament: Any
    stage: Any
    stage_id: Any  # as given in the URL
    erroneous_flatout2_generation_form: Any
    render_form: Callable[..., Any]  # the generation form view


def redirect_to_stage_view(
    party: Party, tournament: Any, stage_id: Any
) -> Response:
    return redirect_to(
        '.view',
        party_id=party.id,
        tournament_id=tournament.id,
        tab='stages',
        stage_id=stage_id,
    )


def get_generation_block_redirect(
    party: Party, tournament: Any, stage: Any
) -> Response | None:
    """Return a redirect (and flash why) if the stage cannot be
    generated now."""
    stages = get_stages_for_tournament(party.id, tournament.id)
    stages_by_id = {stage_item.id: stage_item for stage_item in stages}
    matches_by_stage: dict[StageID, list[Match]] = defaultdict(list)
    for match in get_matches_for_tournament(party.id, tournament.id):
        matches_by_stage[match.stage_id].append(match)
    generation_block_reason = get_stage_generation_block_reason(
        stage,
        stages_by_id,
        matches_by_stage,
    )
    if generation_block_reason:
        flash_error(generation_block_reason)
        return redirect_to_stage_view(party, tournament, stage.id)

    return None


def count_existing_stage_matches(
    party: Party, tournament: Any, stage: Any
) -> int:
    return sum(
        1
        for match in get_matches_for_tournament(party.id, tournament.id)
        if match.stage_id == stage.id
    )


def flash_generation_result(result: Result[list, str]) -> None:
    match result:
        case Ok(matches):
            flash_success(
                gettext(
                    '%(count)s Matches wurden erzeugt.',
                    count=len(matches),
                )
            )
        case Err(message):
            flash_error(message)


def find_redirect_stage_id(party: Party, tournament: Any, stage_id: Any) -> Any:
    """Return the stage to show after generating: the first group
    stage the builder materialized, if any, else the stage itself."""
    refreshed_stage = next(
        (
            candidate_stage
            for candidate_stage in get_stages_for_tournament(
                party.id, tournament.id
            )
            if candidate_stage.id == stage_id
        ),
        None,
    )
    if refreshed_stage is None:
        return stage_id

    materialized_group_stage_ids = (refreshed_stage.settings or {}).get(
        'builder_materialized_group_stage_ids', []
    )
    if not materialized_group_stage_ids:
        return stage_id

    try:
        return UUID(str(materialized_group_stage_ids[0]))
    except TypeError, ValueError:
        return stage_id
