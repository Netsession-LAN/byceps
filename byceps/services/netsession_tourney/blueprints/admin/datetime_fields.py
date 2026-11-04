"""
byceps.services.netsession_tourney.blueprints.admin.datetime_fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Values for `datetime-local` form fields.

Times are stored in UTC, but the fields show (and submitted values are
read as) the user's local time.
"""

from datetime import datetime

from flask_babel import to_user_timezone


def serialize_utc_as_local(value: datetime | None) -> str | None:
    if value is None:
        return None

    return to_user_timezone(value).strftime('%Y-%m-%dT%H:%M')
