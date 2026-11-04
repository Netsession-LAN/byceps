CREATE TABLE IF NOT EXISTS netsession_tourney_tournament_prizes (
  id UUID PRIMARY KEY,
  tournament_id UUID NOT NULL REFERENCES netsession_tourney_tournaments(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  body_format TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  UNIQUE (tournament_id, position)
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_tournament_prizes_tournament_id
  ON netsession_tourney_tournament_prizes (tournament_id);
