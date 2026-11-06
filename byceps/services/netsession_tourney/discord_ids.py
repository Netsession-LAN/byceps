"""
byceps.services.netsession_tourney.discord_ids
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord IDs ("snowflakes") are 17 to 20 digits. Checked when an admin
enters them, so a typo shows up right away and not only when sending
fails later.
"""

from __future__ import annotations

import re


_SNOWFLAKE = re.compile(r'[0-9]{17,20}')


def is_discord_id(value: str | None) -> bool:
    return value is not None and _SNOWFLAKE.fullmatch(value) is not None
