"""
byceps.services.netsession_newsletter.subscriber_queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subscribers of a list with everything the Sendy fields need. Same filter
as upstream `get_subscribers_to_list()`: only initialized, unsuspended,
undeleted accounts with a verified email address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, false, func, select

from byceps.database import db
from byceps.services.newsletter.dbmodels import (
    DbSubscription,
    DbSubscriptionUpdate,
)
from byceps.services.newsletter.models import ListID
from byceps.services.orga_team.dbmodels import DbMembership, DbOrgaTeam
from byceps.services.party.models import PartyID
from byceps.services.user.dbmodels import DbUser, DbUserDetail
from byceps.services.user.models import UserID


@dataclass(frozen=True, kw_only=True)
class SyncSubscriber:
    user_id: UserID
    screen_name: str | None
    email_address: str
    first_name: str | None
    last_name: str | None
    is_orga_member: bool
    subscribed_at: datetime | None


def get_subscribers(
    list_id: ListID,
    current_party_id: PartyID | None,
    *,
    user_id: UserID | None = None,
) -> list[SyncSubscriber]:
    """Subscribers of the list; orga means member of an orga team of the
    current party (none set: nobody is orga)."""
    stmt = (
        select(
            DbUser.id,
            DbUser.screen_name,
            DbUser.email_address,
            DbUserDetail.first_name,
            DbUserDetail.last_name,
            _is_orga_member(current_party_id),
            _subscribed_at(list_id),
        )
        .join(DbSubscription, DbSubscription.user_id == DbUser.id)
        .outerjoin(DbUserDetail, DbUserDetail.user_id == DbUser.id)
        .filter(DbSubscription.list_id == list_id)
        .filter(DbUser.email_address.is_not(None))
        .filter(DbUser.initialized == True)  # noqa: E712
        .filter(DbUser.email_address_verified == True)  # noqa: E712
        .filter(DbUser.suspended == False)  # noqa: E712
        .filter(DbUser.deleted == False)  # noqa: E712
        .order_by(DbUser.email_address)
    )
    if user_id is not None:
        stmt = stmt.filter(DbUser.id == user_id)

    return [
        SyncSubscriber(
            user_id=row[0],
            screen_name=row[1],
            email_address=row[2],
            first_name=row[3],
            last_name=row[4],
            is_orga_member=bool(row[5]),
            subscribed_at=row[6],
        )
        for row in db.session.execute(stmt).tuples()
    ]


def _is_orga_member(current_party_id: PartyID | None):
    if current_party_id is None:
        return false().label('is_orga_member')
    return (
        exists()
        .where(DbMembership.user_id == DbUser.id)
        .where(DbMembership.orga_team_id == DbOrgaTeam.id)
        .where(DbOrgaTeam.party_id == current_party_id)
        .label('is_orga_member')
    )


def _subscribed_at(list_id: ListID):
    """Time of the latest subscription request for the list."""
    return (
        select(func.max(DbSubscriptionUpdate.expressed_at))
        .where(
            and_(
                DbSubscriptionUpdate.user_id == DbUser.id,
                DbSubscriptionUpdate.list_id == list_id,
                DbSubscriptionUpdate._state == 'requested',
            )
        )
        .scalar_subquery()
        .label('subscribed_at')
    )
