"""
byceps.services.netsession_tourney.checkin_reminders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once a tournament's check-in window opens, every active participant gets a
notification (site, browser push, Discord DM – whatever they subscribed
to). Sent once per tournament; the audit log entry `checkin_reminder_sent`
marks it as done. Run regularly by `scripts/netsession_tourney/run_tourney_timers.py`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db

from .dbmodels import DbNetsessionTourneyAuditLog, DbNetsessionTourneyTournament
from .models import TournamentStatus
from .notification_service import append_notifications_for_tournament
from .service_helpers import append_audit_log
from .site_paths import (
    build_site_tournament_overview_path,
)


CHECKIN_REMINDER_KIND = 'checkin_open'


def send_due_checkin_reminders(now: datetime | None = None) -> int:
    """Notify the participants of tournaments whose check-in just opened;
    return the number of tournaments."""
    now = now or datetime.utcnow()
    db_tournaments = db.session.scalars(
        select(DbNetsessionTourneyTournament)
        .filter(DbNetsessionTourneyTournament.status == TournamentStatus.live.value)
        .filter(DbNetsessionTourneyTournament.checkin_open_at <= now)
        .filter(DbNetsessionTourneyTournament.checkin_close_at > now)
    ).all()

    sent = 0
    for db_tournament in db_tournaments:
        if _was_reminded(db_tournament.id):
            continue
        append_notifications_for_tournament(
            db_tournament.id,
            actor_user_id=None,
            kind=CHECKIN_REMINDER_KIND,
            payload={
                'slug': db_tournament.slug,
                'url': build_site_tournament_overview_path(db_tournament.slug),
            },
        )
        append_audit_log(
            actor_user_id=None,
            object_type='tournament',
            object_id=db_tournament.id,
            action='checkin_reminder_sent',
            payload={},
            created_at=now,
        )
        sent += 1

    db.session.commit()
    return sent


def _was_reminded(tournament_id) -> bool:
    return (
        db.session.scalar(
            select(DbNetsessionTourneyAuditLog.id)
            .filter_by(
                object_type='tournament',
                object_id=tournament_id,
                action='checkin_reminder_sent',
            )
            .limit(1)
        )
        is not None
    )
