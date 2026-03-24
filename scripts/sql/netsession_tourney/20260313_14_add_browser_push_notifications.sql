CREATE TABLE IF NOT EXISTS netsession_tourney_browser_push_config (
  party_id TEXT PRIMARY KEY REFERENCES parties (id),
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  vapid_public_key TEXT,
  vapid_private_key_encrypted TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS netsession_tourney_browser_push_subscriptions (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties (id),
  user_id UUID NOT NULL REFERENCES users (id),
  endpoint TEXT NOT NULL,
  endpoint_p256dh TEXT NOT NULL,
  endpoint_auth TEXT NOT NULL,
  user_agent TEXT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  CONSTRAINT netsession_tourney_browser_push_subscriptions_party_endpoint_key
    UNIQUE (party_id, endpoint)
);

CREATE INDEX IF NOT EXISTS netsession_tourney_browser_push_subscriptions_party_idx
  ON netsession_tourney_browser_push_subscriptions (party_id);

CREATE INDEX IF NOT EXISTS netsession_tourney_browser_push_subscriptions_user_idx
  ON netsession_tourney_browser_push_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS netsession_tourney_browser_push_outbox (
  id UUID PRIMARY KEY,
  notification_id UUID NOT NULL UNIQUE REFERENCES netsession_tourney_notifications (id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMP WITHOUT TIME ZONE,
  last_error TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS netsession_tourney_browser_push_outbox_status_idx
  ON netsession_tourney_browser_push_outbox (status);
