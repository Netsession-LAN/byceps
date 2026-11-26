"""
byceps.services.netsession_tourney.blueprints.site.tournament_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ranking of a tournament as the ranking page shows it. Shared by the
site page and the API (standings), so both always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from byceps.services.netsession_tourney.double_grand_final import (
    get_match_results,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import (
    Match,
    MatchResult,
    MatchSlot,
    Participant,
    Stage,
    StageType,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from byceps.services.party.models import PartyID

from .elimination_ranking import rank_by_elimination
from .ranking_helpers import (
    are_all_rankable_matches_completed,
    build_ffa_ranking_rows,
    build_flatout2_ranking_rows,
    build_ranking_rows,
    has_rankable_results,
)
from .stage_filters import (
    uses_only_ffa_scoring_stages,
    uses_only_flatout2_stages,
    uses_only_swiss_stages,
)
from .stage_render_helpers import _get_ffa_placement_by_slot_no


@dataclass(frozen=True, kw_only=True)
class TournamentRanking:
    participants: list[Participant]
    stages: list[Stage]
    matches: list[Match]
    slots_by_match_id: dict[Any, list[MatchSlot]]
    results_by_match_id: dict[Any, MatchResult]
    rows: list[dict]
    has_data: bool
    is_final: bool
    is_ffa_scoring: bool
    is_flatout2: bool
    is_swiss: bool


def compute_tournament_ranking(
    party_id: PartyID, tournament_id
) -> TournamentRanking:
    participants = get_participants_for_tournament(party_id, tournament_id)
    stages = get_stages_for_tournament(party_id, tournament_id)
    matches = get_matches_for_tournament(party_id, tournament_id)
    match_ids = {match.id for match in matches}
    slots_by_match_id = get_match_slots(match_ids)
    results_by_match_id = get_match_results(match_ids)

    is_ffa_scoring = uses_only_ffa_scoring_stages(stages, matches)
    is_flatout2 = uses_only_flatout2_stages(stages, matches)
    is_swiss = uses_only_swiss_stages(stages, matches)
    if is_ffa_scoring:
        rows = build_ffa_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            {stage.id: stage for stage in stages},
        )
    elif is_flatout2:
        rows = build_flatout2_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            _get_ffa_placement_by_slot_no,
        )
    else:
        rows = build_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            stage_type=StageType.swiss if is_swiss else None,
        )
    rows = rank_by_elimination(
        rows, stages, matches, slots_by_match_id, results_by_match_id
    )
    has_data = has_rankable_results(
        matches, slots_by_match_id, results_by_match_id
    )
    is_final = has_data and are_all_rankable_matches_completed(
        matches, slots_by_match_id
    )

    return TournamentRanking(
        participants=participants,
        stages=stages,
        matches=matches,
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        rows=rows,
        has_data=has_data,
        is_final=is_final,
        is_ffa_scoring=is_ffa_scoring,
        is_flatout2=is_flatout2,
        is_swiss=is_swiss,
    )
