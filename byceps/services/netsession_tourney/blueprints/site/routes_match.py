"""
byceps.services.netsession_tourney.blueprints.site.routes_match
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match page: view, result report, chat.
"""

from __future__ import annotations

from flask import (
    abort,
    g,
    redirect,
    request,
)
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    MatchChatMessageForm,
    MatchScoreReportForm,
)
from byceps.services.netsession_tourney.match_chat_service import (
    post_match_chat_message,
)
from byceps.services.netsession_tourney.match_queries import (
    find_match_for_tournament,
)
from byceps.services.netsession_tourney.result_service import report_result
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.views import login_required, redirect_to

from .blueprint import blueprint
from .common import (
    _get_tournament_or_404,
    build_slot_score_payload,
    format_timeline_action,
    get_main_nav_current_page_id,
)
from .match_helpers import (
    _parse_slot_scores,
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    get_or_create_idempotency_key,
)
from .presentation_helpers import (
    get_stage_duration_minutes,
)
from .public_match_page_data import index_stages_by_id
from .routes_match_view_data import (
    build_activity_items,
    compute_match_end_at,
    determine_match_user_permissions,
    find_bye_slot_ids,
    find_current_host_name,
    get_flatout2_round_details,
    get_sorted_match_slots,
    is_ffa_detail_match,
    load_match_activity,
    load_slot_participants,
    load_tournament_matches_with_slots_and_results,
    shows_preliminaries_tab,
)
from .stage_filters import (
    _is_ffa_scoring_stage,
    _is_flatout2_stage,
    uses_only_ffa_simple_stages,
    uses_only_flatout2_stages,
)
from .stage_render_helpers import (
    build_ffa_match_detail_rows,
)


@blueprint.get('/<slug>/matches/<uuid:match_id>')
@templated
def view_match(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = index_stages_by_id(stages)
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    if match is None:
        abort(404)

    matches, slots_by_match_id, results_by_match_id = (
        load_tournament_matches_with_slots_and_results(tournament)
    )
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = (
        build_skipped_double_grand_final_match_ids(
            matches,
            slots_by_match_id,
            results_by_match_id,
            stages_by_id,
        )
    )
    slots = get_sorted_match_slots(match.id)

    bye_slot_ids = find_bye_slot_ids(match, slots)

    has_bye_slot = bool(bye_slot_ids)
    participants_by_id = load_slot_participants(slots)
    result = results_by_match_id.get(match.id)
    slot_scores = _parse_slot_scores(slots, result)
    (
        timeline_entries,
        chat_messages,
        chat_team_by_actor_user_id,
        users_by_id,
    ) = load_match_activity(tournament, match, participants_by_id)
    activity_items = build_activity_items(timeline_entries, chat_messages)

    can_report, can_chat = determine_match_user_permissions(
        tournament, match, slots, participants_by_id, stages_by_id
    )

    is_skipped_double_grand_final = (
        match.id in skipped_double_grand_final_match_ids
    )
    if is_skipped_double_grand_final:
        can_report = False

    stage = stages_by_id.get(match.stage_id)
    is_ffa_scoring_match = _is_ffa_scoring_stage(stage)
    is_flatout2_match = _is_flatout2_stage(stage)
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    ffa_match_rows = []
    if is_ffa_detail_match(is_ffa_scoring_match, is_flatout2_match):
        can_report = False
        ffa_match_rows = build_ffa_match_detail_rows(
            slots,
            participants_by_id,
            users_by_id,
            result,
            slot_scores,
            is_flatout2_match=is_flatout2_match,
        )
    current_host_participant_id, flatout2_round_races = (
        get_flatout2_round_details(match, stage, is_flatout2_match)
    )
    current_host_name = find_current_host_name(
        ffa_match_rows, current_host_participant_id
    )
    stage_duration_minutes = get_stage_duration_minutes(stage)
    match_end_at = compute_match_end_at(match, stage_duration_minutes)

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'match': match,
        'match_label': match_labels_by_id.get(
            match.id, f'{gettext("Match")} #{match.match_no}'
        ),
        'stage': stage,
        'is_ffa_scoring_match': is_ffa_scoring_match,
        'is_flatout2_match': is_flatout2_match,
        'current_host_participant_id': current_host_participant_id,
        'current_host_name': current_host_name,
        'flatout2_round_races': flatout2_round_races,
        'ffa_match_rows': ffa_match_rows,
        'match_end_at': match_end_at,
        'slots': slots,
        'bye_slot_ids': bye_slot_ids,
        'has_bye_slot': has_bye_slot,
        'slot_scores': slot_scores,
        'participants_by_id': participants_by_id,
        'result': result,
        'timeline_entries': timeline_entries,
        'chat_messages': chat_messages,
        'activity_items': activity_items,
        'users_by_id': users_by_id,
        'chat_team_by_actor_user_id': chat_team_by_actor_user_id,
        'format_timeline_action': format_timeline_action,
        'report_form': MatchScoreReportForm(),
        'chat_form': MatchChatMessageForm(),
        'can_report': can_report,
        'can_chat': can_chat,
        'is_skipped_double_grand_final': is_skipped_double_grand_final,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': shows_preliminaries_tab(
            stages, is_flatout2_tournament
        ),
        'current_page': current_page_id,
        'current_tournament_page': 'matches',
    }


@blueprint.post('/<slug>/matches/<uuid:match_id>/report')
@login_required
def report_match_result(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    form = MatchScoreReportForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Ergebnisdaten.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    slots = get_sorted_match_slots(match_id)
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    rejection_message = _get_report_rejection_message(
        tournament, match, slots, form
    )
    if rejection_message is not None:
        flash_error(rejection_message)
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    slot_1_points = form.slot_1_points.data
    slot_2_points = form.slot_2_points.data
    winner_slot = _determine_winner_slot(slots, slot_1_points, slot_2_points)
    score = build_slot_score_payload(
        slots,
        {
            slots[0].slot_no: slot_1_points,
            slots[1].slot_no: slot_2_points,
        },
    )
    ranking = {}
    idempotency_key = get_or_create_idempotency_key(form.idempotency_key.data)
    comment = _get_report_comment(form)

    result = report_result(
        g.party.id,
        tournament.id,
        match_id,
        g.user.id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score=score,
        ranking=ranking,
        actor_is_admin_or_referee=False,
        admin_comment=comment,
    )

    _flash_report_result(result)

    next_target = request.form.get('next')
    if _is_local_redirect_target(next_target):
        return redirect(next_target)

    return redirect_to('.view_match', slug=slug, match_id=match_id)


def _get_report_rejection_message(tournament, match, slots, form) -> str | None:
    if match is None:
        return gettext('Unbekanntes Match.')
    stages_by_id = index_stages_by_id(
        get_stages_for_tournament(g.party.id, tournament.id)
    )
    stage = stages_by_id.get(match.stage_id)
    if _is_ffa_scoring_stage(stage):
        return gettext(
            'FFA-Ergebnisse werden nur im Admin-Bereich eingetragen.'
        )

    return _get_duel_report_rejection_message(slots, form)


def _get_duel_report_rejection_message(slots, form) -> str | None:
    if len(slots) != 2:
        return gettext(
            'Ergebnisübermittlung mit Punkten wird aktuell nur für Duell-Matches unterstützt.'
        )

    if any(slot.participant_id is None for slot in slots):
        return gettext(
            'Beide Teilnehmer müssen gesetzt sein, bevor ein Ergebnis gemeldet werden kann.'
        )

    if form.slot_1_points.data == form.slot_2_points.data:
        return gettext(
            'Ein Unentschieden ist nicht erlaubt. Bitte einen eindeutigen Sieger melden.'
        )

    return None


def _determine_winner_slot(slots, slot_1_points, slot_2_points):
    return (
        slots[0].slot_no if slot_1_points > slot_2_points else slots[1].slot_no
    )


def _get_report_comment(form):
    return form.comment.data.strip() if form.comment.data else None


def _flash_report_result(result) -> None:
    if result.is_ok():
        flash_success(gettext('Ergebnis wurde übermittelt.'))
    else:
        flash_error(result.unwrap_err())


def _is_local_redirect_target(next_target):
    return (
        next_target
        and next_target.startswith('/')
        and not next_target.startswith('//')
    )


@blueprint.post('/<slug>/matches/<uuid:match_id>/chat')
@login_required
def post_match_chat(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    form = MatchChatMessageForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Chat-Nachricht.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    is_admin_or_referee = g.user.has_permission(
        'netsession_tourney.manage'
    ) or g.user.has_permission('netsession_tourney.admin')

    result = post_match_chat_message(
        g.party.id,
        tournament.id,
        match_id,
        g.user.id,
        form.body.data,
        actor_is_admin_or_referee=is_admin_or_referee,
    )
    if result.is_ok():
        flash_success(gettext('Nachricht wurde gesendet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_match', slug=slug, match_id=match_id)
