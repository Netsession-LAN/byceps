CREATE TABLE IF NOT EXISTS netsession_tourney_logo_assets (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id),
  filename TEXT NOT NULL,
  label TEXT NOT NULL,
  uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_netsession_tourney_logo_assets_party_filename
  ON netsession_tourney_logo_assets (party_id, filename);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_logo_assets_party_id
  ON netsession_tourney_logo_assets (party_id);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_logo_assets_uploaded_by_user_id
  ON netsession_tourney_logo_assets (uploaded_by_user_id);
