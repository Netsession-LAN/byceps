ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS logo_url TEXT;


CREATE TABLE IF NOT EXISTS netsession_tourney_match_chat_messages (
  id UUID PRIMARY KEY,
  tournament_id UUID NOT NULL REFERENCES netsession_tourney_tournaments(id),
  match_id UUID NOT NULL REFERENCES netsession_tourney_matches(id),
  actor_user_id UUID NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_match_chat_messages_tournament_id
  ON netsession_tourney_match_chat_messages (tournament_id);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_match_chat_messages_match_id
  ON netsession_tourney_match_chat_messages (match_id);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_match_chat_messages_actor_user_id
  ON netsession_tourney_match_chat_messages (actor_user_id);
