ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS discord_dm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS discord_dm_event_mask JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS netsession_tourney_discord_dm_config (
  party_id TEXT PRIMARY KEY REFERENCES parties (id),
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  application_id TEXT,
  bot_token_encrypted TEXT,
  default_event_mask JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS netsession_tourney_discord_dm_subscriptions (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties (id),
  user_id UUID NOT NULL REFERENCES users (id),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  CONSTRAINT netsession_tourney_discord_dm_subscriptions_party_user_key
    UNIQUE (party_id, user_id)
);

CREATE INDEX IF NOT EXISTS netsession_tourney_discord_dm_subscriptions_party_idx
  ON netsession_tourney_discord_dm_subscriptions (party_id);

CREATE INDEX IF NOT EXISTS netsession_tourney_discord_dm_subscriptions_user_idx
  ON netsession_tourney_discord_dm_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS netsession_tourney_discord_dm_outbox (
  id UUID PRIMARY KEY,
  notification_id UUID NOT NULL UNIQUE REFERENCES netsession_tourney_notifications (id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMP WITHOUT TIME ZONE,
  last_error TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS netsession_tourney_discord_dm_outbox_status_idx
  ON netsession_tourney_discord_dm_outbox (status);
