ALTER TABLE netsession_tourney_matches
  ADD COLUMN IF NOT EXISTS settings_json JSONB NOT NULL DEFAULT '{}'::jsonb;
