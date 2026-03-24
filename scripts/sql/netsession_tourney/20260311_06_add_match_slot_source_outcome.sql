ALTER TABLE netsession_tourney_match_slots
  ADD COLUMN IF NOT EXISTS source_outcome TEXT;

ALTER TABLE netsession_tourney_match_slots
  ALTER COLUMN source_outcome SET DEFAULT 'winner';

UPDATE netsession_tourney_match_slots
SET source_outcome = 'winner'
WHERE source_outcome IS NULL;

ALTER TABLE netsession_tourney_match_slots
  ALTER COLUMN source_outcome SET NOT NULL;
