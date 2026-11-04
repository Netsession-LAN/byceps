# Netsession SQL migrations

SQL files in this directory (and in `scripts/sql/netsession_tourney/`) are
applied automatically on deploy by `scripts/netsession_deploy/migrate.sh`,
ordered by file name, each exactly once.

Naming: `YYYYMMDD_NN_short_description.sql`, e.g.
`20261110_01_upstream_add_user_group_columns.sql`.

When merging upstream BYCEPS: its schema changes are published as SQL
snippets in the changelog / `docs/upgrading`, not as files. Copy each one into
a new file here as part of the merge, otherwise the deploy won't apply it.

Never edit a file that has already been deployed; add a new one instead.
