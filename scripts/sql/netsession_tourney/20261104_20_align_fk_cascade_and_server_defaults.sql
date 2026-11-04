-- Align tournament tables created from the SQLAlchemy models (e.g. prod,
-- via `byceps create-database-tables`) with those created by the earlier SQL
-- migrations (e.g. test): ON DELETE CASCADE on five foreign keys and the
-- server-side column defaults. Idempotent; a no-op where already aligned.

-- 1. Foreign keys: find by table/column (constraint names differ between
--    databases) and recreate with ON DELETE CASCADE only if missing.
DO $$
DECLARE
  fk RECORD;
  con RECORD;
BEGIN
  FOR fk IN
    SELECT * FROM (VALUES
      ('netsession_tourney_tournament_prizes',  'tournament_id',   'netsession_tourney_tournaments'),
      ('netsession_tourney_tournament_admins',  'tournament_id',   'netsession_tourney_tournaments'),
      ('netsession_tourney_tournament_admins',  'user_id',         'users'),
      ('netsession_tourney_browser_push_outbox','notification_id', 'netsession_tourney_notifications'),
      ('netsession_tourney_discord_dm_outbox',  'notification_id', 'netsession_tourney_notifications')
    ) AS t(tbl, col, ref)
  LOOP
    FOR con IN
      SELECT c.conname, c.confdeltype
      FROM pg_constraint c
      JOIN pg_attribute a
        ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
      WHERE c.contype = 'f'
        AND c.conrelid = fk.tbl::regclass
        AND c.confrelid = fk.ref::regclass
        AND array_length(c.conkey, 1) = 1
        AND a.attname = fk.col
    LOOP
      IF con.confdeltype <> 'c' THEN
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', fk.tbl, con.conname);
        EXECUTE format(
          'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES %I (id) ON DELETE CASCADE',
          fk.tbl, con.conname, fk.col, fk.ref
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;

-- 2. Server-side defaults (as declared by the original SQL migrations).
ALTER TABLE netsession_tourney_browser_push_config
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW(),
  ALTER COLUMN enabled SET DEFAULT FALSE;

ALTER TABLE netsession_tourney_browser_push_outbox
  ALTER COLUMN attempt_count SET DEFAULT 0,
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE netsession_tourney_browser_push_subscriptions
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW(),
  ALTER COLUMN last_seen_at SET DEFAULT NOW(),
  ALTER COLUMN enabled SET DEFAULT TRUE;

ALTER TABLE netsession_tourney_coin_ledger
  ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE netsession_tourney_coin_settings
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW(),
  ALTER COLUMN default_coin_amount SET DEFAULT 0,
  ALTER COLUMN enabled SET DEFAULT FALSE;

ALTER TABLE netsession_tourney_ticket_category_coin_settings
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE netsession_tourney_discord_dm_config
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW(),
  ALTER COLUMN default_event_mask SET DEFAULT '[]'::jsonb,
  ALTER COLUMN enabled SET DEFAULT FALSE;

ALTER TABLE netsession_tourney_discord_dm_outbox
  ALTER COLUMN attempt_count SET DEFAULT 0,
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE netsession_tourney_discord_dm_subscriptions
  ALTER COLUMN created_at SET DEFAULT NOW(),
  ALTER COLUMN updated_at SET DEFAULT NOW(),
  ALTER COLUMN last_seen_at SET DEFAULT NOW(),
  ALTER COLUMN enabled SET DEFAULT TRUE;

ALTER TABLE netsession_tourney_discord_forum_image_assets
  ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE netsession_tourney_match_slots
  ALTER COLUMN source_outcome SET DEFAULT 'winner';

ALTER TABLE netsession_tourney_matches
  ALTER COLUMN settings_json SET DEFAULT '{}'::jsonb;

ALTER TABLE netsession_tourney_tournaments
  ALTER COLUMN coin_charge_mode SET DEFAULT 'captain_only',
  ALTER COLUMN coin_cost SET DEFAULT 0,
  ALTER COLUMN coin_refund_policy SET DEFAULT 'until_tournament_end',
  ALTER COLUMN discord_dm_enabled SET DEFAULT FALSE,
  ALTER COLUMN discord_dm_event_mask SET DEFAULT '[]'::jsonb,
  ALTER COLUMN is_sponsored SET DEFAULT FALSE,
  ALTER COLUMN visible_on_site SET DEFAULT TRUE;
