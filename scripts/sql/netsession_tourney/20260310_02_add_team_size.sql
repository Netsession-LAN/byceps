-- Netsession Tourney migration: add team size requirement to tournaments
ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS team_size INTEGER;
