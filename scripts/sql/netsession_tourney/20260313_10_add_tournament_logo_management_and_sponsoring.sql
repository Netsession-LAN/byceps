CREATE TABLE IF NOT EXISTS netsession_tourney_tournament_logo_assets (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id),
  filename TEXT NOT NULL,
  label TEXT NOT NULL,
  uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  UNIQUE (party_id, filename)
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_tournament_logo_assets_party_id
  ON netsession_tourney_tournament_logo_assets (party_id);


CREATE TABLE IF NOT EXISTS netsession_tourney_sponsor_logo_assets (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id),
  filename TEXT NOT NULL,
  label TEXT NOT NULL,
  uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  UNIQUE (party_id, filename)
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_sponsor_logo_assets_party_id
  ON netsession_tourney_sponsor_logo_assets (party_id);


ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS is_sponsored BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS sponsor_logo_url TEXT;
