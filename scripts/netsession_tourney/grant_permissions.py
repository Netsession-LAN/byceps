"""Grant Netsession tournament permissions to a role and optional user.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from pathlib import Path
import sys

import click

from byceps.services.authz import authz_service
from byceps.services.authz.models import PermissionID, RoleID

sys.path.append(str(Path(__file__).resolve().parents[1]))

from _util import call_with_app_context
from _validators import validate_user_screen_name


DEFAULT_ROLE_ID = 'netsession_tourney_admin'
DEFAULT_ROLE_TITLE = 'Netsession-Turniere verwalten'
NETSESSION_PERMISSION_IDS = [
    PermissionID('netsession_tourney.view'),
    PermissionID('netsession_tourney.participate'),
    PermissionID('netsession_tourney.report_result'),
    PermissionID('netsession_tourney.manage'),
    PermissionID('netsession_tourney.admin'),
]


@click.command()
@click.option('--role-id', default=DEFAULT_ROLE_ID, show_default=True)
@click.option('--role-title', default=DEFAULT_ROLE_TITLE, show_default=True)
@click.option(
    '--assign-to',
    callback=validate_user_screen_name,
    help='Screen name of the user to assign the role to.',
)
def execute(role_id: str, role_title: str, assign_to) -> None:
    role_id_obj = RoleID(role_id)

    role = authz_service.find_role(role_id_obj)
    if role is None:
        role_result = authz_service.create_role(role_id_obj, role_title)
        if role_result.is_err():
            click.secho('Could not create role.', fg='red')
            return
        click.secho(f'Created role "{role_id}".', fg='green')
    else:
        click.echo(f'Using existing role "{role_id}".')

    assigned_permission_ids = authz_service.get_permission_ids_for_role(
        role_id_obj
    )
    for permission_id in NETSESSION_PERMISSION_IDS:
        if permission_id in assigned_permission_ids:
            continue
        authz_service.assign_permission_to_role(permission_id, role_id_obj)
        click.secho(f'Assigned permission "{permission_id}".', fg='green')

    if assign_to is not None:
        event = authz_service.assign_role_to_user(role_id_obj, assign_to)
        if event is None:
            click.echo(
                f'Role "{role_id}" already assigned to user '
                f'"{assign_to.screen_name}".'
            )
        else:
            click.secho(
                f'Assigned role "{role_id}" to user "{assign_to.screen_name}".',
                fg='green',
            )


if __name__ == '__main__':
    call_with_app_context(execute)
