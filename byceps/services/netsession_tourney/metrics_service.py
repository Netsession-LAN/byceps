"""
byceps.services.netsession_tourney.metrics_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

from sqlalchemy import select

from byceps.database import db
from byceps.services.metrics.models import Label, Metric

from .dbmodels import (
    DbNetsessionTourneyApiRequestMetric,
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .models import DiscordOutboxStatus, MatchState


def collect_metrics() -> Iterator[Metric]:
    now = datetime.utcnow()

    yield from _collect_tournament_count_per_party()
    yield from _collect_participant_count_per_party()
    yield from _collect_match_state_counts_per_party()
    yield from _collect_discord_outbox_counts_per_party()
    yield from _collect_discord_queue_lag_per_party(now)
    yield from _collect_api_error_and_latency_metrics(now)


def _collect_tournament_count_per_party() -> Iterator[Metric]:
    rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            db.func.count(DbNetsessionTourneyTournament.id),
        ).group_by(DbNetsessionTourneyTournament.party_id)
    ).all()

    for party_id, count in rows:
        yield Metric(
            'netsession_tourney_tournament_count',
            count,
            labels=[Label('party', party_id)],
        )


def _collect_participant_count_per_party() -> Iterator[Metric]:
    rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            db.func.count(DbNetsessionTourneyParticipant.id),
        )
        .join(
            DbNetsessionTourneyParticipant,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyParticipant.tournament_id,
        )
        .group_by(DbNetsessionTourneyTournament.party_id)
    ).all()

    for party_id, count in rows:
        yield Metric(
            'netsession_tourney_participant_count',
            count,
            labels=[Label('party', party_id)],
        )


def _collect_match_state_counts_per_party() -> Iterator[Metric]:
    rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            DbNetsessionTourneyMatch.state,
            db.func.count(DbNetsessionTourneyMatch.id),
        )
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyMatch.tournament_id,
        )
        .group_by(
            DbNetsessionTourneyTournament.party_id,
            DbNetsessionTourneyMatch.state,
        )
    ).all()

    for party_id, state, count in rows:
        labels = [Label('party', party_id), Label('state', state)]
        yield Metric('netsession_tourney_match_count', count, labels=labels)

    # Derived signal used as failed result reports indicator.
    failed_rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            db.func.count(DbNetsessionTourneyMatch.id),
        )
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyMatch.tournament_id,
        )
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [
                    MatchState.needs_admin_review.value,
                    MatchState.disputed.value,
                ]
            )
        )
        .group_by(DbNetsessionTourneyTournament.party_id)
    ).all()

    for party_id, count in failed_rows:
        yield Metric(
            'netsession_tourney_failed_result_report_count',
            count,
            labels=[Label('party', party_id)],
        )


def _collect_discord_outbox_counts_per_party() -> Iterator[Metric]:
    rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            DbNetsessionTourneyDiscordOutbox.status,
            db.func.count(DbNetsessionTourneyDiscordOutbox.id),
        )
        .join(
            DbNetsessionTourneyDiscordOutbox,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyDiscordOutbox.tournament_id,
        )
        .group_by(
            DbNetsessionTourneyTournament.party_id,
            DbNetsessionTourneyDiscordOutbox.status,
        )
    ).all()

    for party_id, status, count in rows:
        yield Metric(
            'netsession_tourney_discord_outbox_count',
            count,
            labels=[Label('party', party_id), Label('status', status)],
        )

    failed_rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            db.func.count(DbNetsessionTourneyDiscordOutbox.id),
        )
        .join(
            DbNetsessionTourneyDiscordOutbox,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyDiscordOutbox.tournament_id,
        )
        .filter(
            DbNetsessionTourneyDiscordOutbox.status.in_(
                [
                    DiscordOutboxStatus.failed.value,
                    DiscordOutboxStatus.dead_letter.value,
                ]
            )
        )
        .group_by(DbNetsessionTourneyTournament.party_id)
    ).all()

    for party_id, count in failed_rows:
        yield Metric(
            'netsession_tourney_failed_discord_post_count',
            count,
            labels=[Label('party', party_id)],
        )


def _collect_discord_queue_lag_per_party(now: datetime) -> Iterator[Metric]:
    rows = db.session.execute(
        select(
            DbNetsessionTourneyTournament.party_id,
            db.func.min(DbNetsessionTourneyDiscordOutbox.created_at),
        )
        .join(
            DbNetsessionTourneyDiscordOutbox,
            DbNetsessionTourneyTournament.id
            == DbNetsessionTourneyDiscordOutbox.tournament_id,
        )
        .filter(
            DbNetsessionTourneyDiscordOutbox.status.in_(
                [
                    DiscordOutboxStatus.pending.value,
                    DiscordOutboxStatus.failed.value,
                ]
            )
        )
        .group_by(DbNetsessionTourneyTournament.party_id)
    ).all()

    for party_id, oldest_created_at in rows:
        if oldest_created_at is None:
            lag_seconds = 0.0
        else:
            lag_seconds = max(0.0, (now - oldest_created_at).total_seconds())

        yield Metric(
            'netsession_tourney_discord_queue_lag_seconds',
            lag_seconds,
            labels=[Label('party', party_id)],
        )


def _collect_api_error_and_latency_metrics(now: datetime) -> Iterator[Metric]:
    window_start = now - timedelta(minutes=5)

    totals = db.session.execute(
        select(
            DbNetsessionTourneyApiRequestMetric.endpoint,
            db.func.count(DbNetsessionTourneyApiRequestMetric.id),
        )
        .filter(DbNetsessionTourneyApiRequestMetric.created_at >= window_start)
        .group_by(DbNetsessionTourneyApiRequestMetric.endpoint)
    ).all()
    totals_by_endpoint = {endpoint: count for endpoint, count in totals}

    errors = db.session.execute(
        select(
            DbNetsessionTourneyApiRequestMetric.endpoint,
            db.func.count(DbNetsessionTourneyApiRequestMetric.id),
        )
        .filter(DbNetsessionTourneyApiRequestMetric.created_at >= window_start)
        .filter(DbNetsessionTourneyApiRequestMetric.status_code >= 500)
        .group_by(DbNetsessionTourneyApiRequestMetric.endpoint)
    ).all()
    errors_by_endpoint = {endpoint: count for endpoint, count in errors}

    for endpoint, total_count in totals_by_endpoint.items():
        if total_count <= 0:
            continue
        error_count = errors_by_endpoint.get(endpoint, 0)
        error_rate_percent = (error_count / total_count) * 100.0
        yield Metric(
            'netsession_tourney_api_error_rate_percent',
            error_rate_percent,
            labels=[Label('endpoint', endpoint)],
        )

    p95_rows = db.session.execute(
        select(
            DbNetsessionTourneyApiRequestMetric.endpoint,
            db.func.percentile_cont(0.95).within_group(
                DbNetsessionTourneyApiRequestMetric.duration_ms
            ),
        )
        .filter(DbNetsessionTourneyApiRequestMetric.created_at >= window_start)
        .group_by(DbNetsessionTourneyApiRequestMetric.endpoint)
    ).all()

    for endpoint, p95 in p95_rows:
        if p95 is None:
            continue
        yield Metric(
            'netsession_tourney_api_latency_p95_ms',
            float(p95),
            labels=[Label('endpoint', endpoint)],
        )
