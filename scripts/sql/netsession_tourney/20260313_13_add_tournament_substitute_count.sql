ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS substitute_count INTEGER;

UPDATE netsession_tourney_tournaments
SET substitute_count = 0
WHERE substitute_count IS NULL;
