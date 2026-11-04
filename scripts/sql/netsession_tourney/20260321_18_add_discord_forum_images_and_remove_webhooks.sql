CREATE TABLE IF NOT EXISTS netsession_tourney_discord_forum_image_assets (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties (id),
  filename TEXT NOT NULL,
  label TEXT NOT NULL,
  uploaded_by_user_id UUID NOT NULL REFERENCES users (id),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  CONSTRAINT netsession_tourney_discord_forum_image_assets_party_filename_key
    UNIQUE (party_id, filename)
);

CREATE INDEX IF NOT EXISTS netsession_tourney_discord_forum_image_assets_party_idx
  ON netsession_tourney_discord_forum_image_assets (party_id);

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS discord_forum_image_url TEXT;

ALTER TABLE netsession_tourney_tournaments
  DROP COLUMN IF EXISTS discord_webhook_url_encrypted;
