"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_match_view
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Route to show a single match of a tournament (see `routes_tournament`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import request, url_for
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    double_grand_final,
    match_queries,
    tournament_queries,
)
from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_match_or_404,
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    is_flatout2_stage_type,
)
from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    build_match_labels,
)
from byceps.services.netsession_tourney.flatout2 import get_flatout2_mode_label
from byceps.services.netsession_tourney.forms import MatchDisputeForm
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required


def _is_flatout2_stage(stage: Any) -> bool:
    return stage is not None and is_flatout2_stage_type(stage.type)


def _get_current_host_participant_id(
    match: Any, is_flatout2_stage: bool
) -> str:
    return (
        str((match.settings or {}).get('host_participant_id') or '').strip()
        if is_flatout2_stage
        else ''
    )


def _with_mode_label(race: dict[str, Any]) -> dict[str, Any]:
    return {
        **race,
        'mode_label': get_flatout2_mode_label(
            str(race.get('mode') or '').strip() or 'single_race'
        ),
    }


def _build_flatout2_round_races(
    match: Any, is_flatout2_stage: bool
) -> list[Any]:
    if not is_flatout2_stage:
        return []

    flatout2_round_races = (match.settings or {}).get('flatout2_races', [])
    return [
        _with_mode_label(race)
        for race in flatout2_round_races
        if isinstance(race, dict)
    ]


def _get_return_to() -> str:
    return_to = (request.args.get('return_to') or 'matches').strip().lower()
    if return_to not in {'stages', 'matches'}:
        return_to = 'matches'
    return return_to


def _build_back_link(
    party_id: Any, tournament_id: Any, stage: Any, return_to: str
) -> tuple[Any, str, str]:
    """Return stage ID, URL and label of the link back to the tournament."""
    if return_to == 'stages':
        back_stage_id = stage.id if stage is not None else None
        back_url = url_for(
            '.view',
            party_id=party_id,
            tournament_id=tournament_id,
            tab='stages',
            stage_id=back_stage_id,
        )
        return back_stage_id, back_url, gettext('Zurück zu Phasen')

    back_url = url_for(
        '.view',
        party_id=party_id,
        tournament_id=tournament_id,
        tab='matches',
    )
    return None, back_url, gettext('Zurück zu Matches')


def register_match_view_routes(blueprint) -> None:
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>'
    )
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/match/view')
    def match_view(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        match = get_match_or_404(party.id, tournament.id, match_id)

        participants = tournament_queries.get_participants_for_tournament(
            party.id, tournament.id
        )
        participants_by_id = {
            participant.id: participant for participant in participants
        }
        all_matches = match_queries.get_matches_for_tournament(
            party.id, tournament.id
        )
        all_slots_by_match_id = match_queries.get_match_slots(
            {item.id for item in all_matches}
        )
        slots = all_slots_by_match_id.get(match.id, [])
        results_by_match_id = double_grand_final.get_match_results({match.id})
        result = results_by_match_id.get(match.id)
        stages = tournament_queries.get_stages_for_tournament(
            party.id, tournament.id
        )
        stages_by_id = {stage.id: stage for stage in stages}
        stage = stages_by_id.get(match.stage_id)
        is_flatout2_stage = _is_flatout2_stage(stage)
        current_host_participant_id = _get_current_host_participant_id(
            match, is_flatout2_stage
        )
        flatout2_round_races = _build_flatout2_round_races(
            match, is_flatout2_stage
        )
        match_label = build_match_labels(
            all_matches,
            all_slots_by_match_id,
            stages_by_id,
        ).get(match.id, gettext('Match #%(match_no)s', match_no=match.match_no))
        return_to = _get_return_to()
        back_stage_id, back_url, back_label = _build_back_link(
            party.id, tournament.id, stage, return_to
        )

        return {
            'party': party,
            'tournament': tournament,
            'stage': stage,
            'match': match,
            'match_label': match_label,
            'participants': participants,
            'participants_by_id': participants_by_id,
            'slots': slots,
            'result': result,
            'is_flatout2_stage': is_flatout2_stage,
            'flatout2_round_races': flatout2_round_races,
            'current_host_participant_id': current_host_participant_id,
            'back_url': back_url,
            'back_label': back_label,
            'parent_return_to': return_to,
            'parent_stage_id': back_stage_id,
            'match_dispute_form': MatchDisputeForm(
                data={'reason_code': 'admin_dispute'}
            ),
        }
