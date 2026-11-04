-- Netsession Tourney migration: add participant limit to tournaments
ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS participant_limit INTEGER;
