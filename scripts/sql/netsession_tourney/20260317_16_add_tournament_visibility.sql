ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS visible_on_site BOOLEAN NOT NULL DEFAULT TRUE;
