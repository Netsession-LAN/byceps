"""
byceps.services.netsession_tourney.blueprints.site.routes_match
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match page: view, result report, chat.
"""

from __future__ import annotations

from datetime import timedelta

from flask import (
    abort,
    g,
    redirect,
    request,
)
from flask_babel import gettext

from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.views import login_required, redirect_to

from ...double_grand_final import get_match_results
from ...flatout2 import get_flatout2_mode_label
from ...forms import (
    MatchChatMessageForm,
    MatchScoreReportForm,
)
from ...match_chat_service import (
    can_user_access_match_chat,
    get_match_chat_messages,
    post_match_chat_message,
)
from ...match_queries import (
    find_match_for_tournament,
    get_match_slots,
    get_match_slots_for_match,
    get_match_timeline_entries,
    get_matches_for_tournament,
)
from ...models import (
    MatchState,
    ParticipantType,
)
from ...registration_validation import get_team_members_for_participants
from ...result_report_mode import is_stage_result_reporting_admin_only
from ...result_service import report_result
from ...tournament_queries import (
    get_stages_for_tournament,
)
from .builder_helpers import get_materialized_builder_container_stages
from .match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    get_or_create_idempotency_key,
    _parse_slot_scores,
)
from .presentation_helpers import (
    get_stage_duration_minutes,
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
from .user_state_helpers import (
    can_user_report_match_result,
)

from .blueprint import blueprint
from .common import (
    get_main_nav_current_page_id,
    _get_tournament_or_404,
    build_slot_score_payload,
    get_participants_for_tournament_indexed_by_id,
    format_timeline_action,
)


@blueprint.get('/<slug>/matches/<uuid:match_id>')
@templated
def view_match(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    if match is None:
        abort(404)

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({item.id for item in matches})
    results_by_match_id = get_match_results({item.id for item in matches})
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = build_skipped_double_grand_final_match_ids(
        matches,
        slots_by_match_id,
        results_by_match_id,
        stages_by_id,
    )
    slots = sorted(
        get_match_slots_for_match(match.id), key=lambda slot: slot.slot_no
    )

    bye_slot_ids = set()
    for slot in slots:
        is_explicit_bye = (
            slot.participant_id is None
            and slot.source_match_slot_id is None
            and match.state == MatchState.completed
        )
        if is_explicit_bye:
            bye_slot_ids.add(slot.id)

    has_bye_slot = bool(bye_slot_ids)
    participants_by_id = get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {slot.participant_id for slot in slots if slot.participant_id},
    )
    result = results_by_match_id.get(match.id)
    slot_scores = _parse_slot_scores(slots, result)
    timeline_entries = get_match_timeline_entries(
        g.party.id, tournament.id, match.id
    )
    timeline_actor_ids = {
        entry['actor_user_id'] for entry in timeline_entries if entry['actor_user_id']
    }
    chat_messages = get_match_chat_messages(g.party.id, tournament.id, match.id)
    chat_actor_ids = {message.actor_user_id for message in chat_messages}
    members_by_participant_id = get_team_members_for_participants(
        set(participants_by_id.keys())
    )
    chat_team_by_actor_user_id = {}
    for participant in participants_by_id.values():
        if participant.type is not ParticipantType.team:
            continue

        if participant.manager_user_id is not None:
            chat_team_by_actor_user_id.setdefault(
                participant.manager_user_id, participant
            )

        for member in members_by_participant_id.get(participant.id, []):
            chat_team_by_actor_user_id.setdefault(member.user_id, participant)

    users_by_id = user_service.get_users_indexed_by_id(
        timeline_actor_ids | chat_actor_ids, include_avatars=True
    )
    activity_items = [
        {
            'kind': 'event',
            'created_at': entry['created_at'],
            'entry': entry,
        }
        for entry in timeline_entries
    ] + [
        {
            'kind': 'chat',
            'created_at': message.created_at,
            'message': message,
        }
        for message in chat_messages
    ]
    activity_items.sort(key=lambda item: item['created_at'])

    can_report = False
    can_chat = False
    user = getattr(g, 'user', None)
    if user is not None and user.authenticated:
        is_admin_or_referee = user.has_permission(
            'netsession_tourney.manage'
        ) or user.has_permission('netsession_tourney.admin')
        can_report = can_user_report_match_result(
            user.id,
            tournament,
            match,
            slots,
            participants_by_id,
            is_admin_or_referee=False,
            admin_only=is_stage_result_reporting_admin_only(
                stages_by_id.get(match.stage_id)
            ),
        )
        can_chat = can_user_access_match_chat(
            g.party.id,
            tournament.id,
            match.id,
            user.id,
            is_admin_or_referee=is_admin_or_referee,
        )

    is_skipped_double_grand_final = match.id in skipped_double_grand_final_match_ids
    if is_skipped_double_grand_final:
        can_report = False

    stage = stages_by_id.get(match.stage_id)
    is_ffa_scoring_match = _is_ffa_scoring_stage(stage)
    is_flatout2_match = _is_flatout2_stage(stage)
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    ffa_match_rows = []
    current_host_participant_id = ''
    flatout2_round_races = []
    if is_ffa_scoring_match or is_flatout2_match:
        can_report = False
        ffa_match_rows = build_ffa_match_detail_rows(
            slots,
            participants_by_id,
            users_by_id,
            result,
            slot_scores,
            is_flatout2_match=is_flatout2_match,
        )
    if is_flatout2_match and stage is not None:
        current_host_participant_id = str(
            (match.settings or {}).get('host_participant_id') or ''
        ).strip()
        raw_flatout2_round_races = (match.settings or {}).get(
            'flatout2_races'
        ) or []
        flatout2_round_races = [
            {
                **race,
                'mode_label': get_flatout2_mode_label(
                    str(race.get('mode') or '').strip() or 'single_race'
                ),
            }
            for race in raw_flatout2_round_races
            if isinstance(race, dict)
        ]
    current_host_name = next(
        (
            row['name']
            for row in ffa_match_rows
            if row.get('participant') is not None
            and str(row['participant'].id) == current_host_participant_id
        ),
        None,
    )
    stage_duration_minutes = get_stage_duration_minutes(stage)
    match_end_at = (
        match.scheduled_at + timedelta(minutes=stage_duration_minutes)
        if match.scheduled_at is not None and stage_duration_minutes is not None
        else None
    )

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
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
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

    slots = sorted(
        get_match_slots_for_match(match_id), key=lambda slot: slot.slot_no
    )
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    if match is None:
        flash_error(gettext('Unbekanntes Match.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)
    stages_by_id = {
        stage.id: stage for stage in get_stages_for_tournament(g.party.id, tournament.id)
    }
    stage = stages_by_id.get(match.stage_id)
    if _is_ffa_scoring_stage(stage):
        flash_error(
            gettext(
                'FFA-Ergebnisse werden nur im Admin-Bereich eingetragen.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    if len(slots) != 2:
        flash_error(
            gettext(
                'Ergebnisübermittlung mit Punkten wird aktuell nur für Duell-Matches unterstützt.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    if any(slot.participant_id is None for slot in slots):
        flash_error(
            gettext(
                'Beide Teilnehmer müssen gesetzt sein, bevor ein Ergebnis gemeldet werden kann.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    slot_1_points = form.slot_1_points.data
    slot_2_points = form.slot_2_points.data
    if slot_1_points == slot_2_points:
        flash_error(
            gettext(
                'Ein Unentschieden ist nicht erlaubt. Bitte einen eindeutigen Sieger melden.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    winner_slot = (
        slots[0].slot_no if slot_1_points > slot_2_points else slots[1].slot_no
    )
    score = build_slot_score_payload(
        slots,
        {
            slots[0].slot_no: slot_1_points,
            slots[1].slot_no: slot_2_points,
        },
    )
    ranking = {}
    idempotency_key = get_or_create_idempotency_key(form.idempotency_key.data)
    comment = form.comment.data.strip() if form.comment.data else None

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

    if result.is_ok():
        flash_success(gettext('Ergebnis wurde übermittelt.'))
    else:
        flash_error(result.unwrap_err())

    next_target = request.form.get('next')
    if next_target and next_target.startswith('/') and not next_target.startswith('//'):
        return redirect(next_target)

    return redirect_to('.view_match', slug=slug, match_id=match_id)


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
