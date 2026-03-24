CREATE TABLE IF NOT EXISTS netsession_tourney_tournament_admins (
  id UUID PRIMARY KEY,
  tournament_id UUID NOT NULL REFERENCES netsession_tourney_tournaments (id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  UNIQUE (tournament_id, user_id)
);

CREATE INDEX IF NOT EXISTS netsession_tourney_tournament_admins_tournament_idx
  ON netsession_tourney_tournament_admins (tournament_id);

CREATE INDEX IF NOT EXISTS netsession_tourney_tournament_admins_user_idx
  ON netsession_tourney_tournament_admins (user_id);
