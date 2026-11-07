"""Every audited action also goes to the server log (without its payload,
which may contain comments or personal data)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from byceps.services.netsession_tourney import service_helpers


def test_audited_action_is_logged_without_payload():
    log = MagicMock()
    object_id, actor_id = uuid4(), uuid4()

    with (
        patch.object(service_helpers, 'db'),
        patch.object(service_helpers, 'log', log),
    ):
        service_helpers.append_audit_log(
            actor_user_id=actor_id,
            object_type='match',
            object_id=object_id,
            action='result_deleted_by_admin',
            payload={'comment': 'private remark'},
            created_at=datetime.utcnow(),
        )

    log.info.assert_called_once_with(
        'netsession_tourney.audit',
        action='result_deleted_by_admin',
        object_type='match',
        object_id=str(object_id),
        actor_user_id=str(actor_id),
    )
