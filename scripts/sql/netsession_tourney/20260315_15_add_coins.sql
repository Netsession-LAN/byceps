CREATE TABLE IF NOT EXISTS netsession_tourney_coin_settings (
  party_id TEXT PRIMARY KEY REFERENCES parties (id),
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  default_coin_amount INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS netsession_tourney_ticket_category_coin_settings (
  party_id TEXT NOT NULL REFERENCES parties (id),
  ticket_category_id UUID NOT NULL REFERENCES ticket_categories (id),
  coin_amount INTEGER NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  PRIMARY KEY (party_id, ticket_category_id)
);

CREATE TABLE IF NOT EXISTS netsession_tourney_coin_ledger (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties (id),
  user_id UUID NOT NULL REFERENCES users (id),
  amount_delta INTEGER NOT NULL,
  kind TEXT NOT NULL,
  reference_type TEXT,
  reference_id TEXT,
  note TEXT,
  created_by_user_id UUID REFERENCES users (id),
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS netsession_tourney_coin_ledger_party_idx
  ON netsession_tourney_coin_ledger (party_id);

CREATE INDEX IF NOT EXISTS netsession_tourney_coin_ledger_user_idx
  ON netsession_tourney_coin_ledger (user_id);

CREATE INDEX IF NOT EXISTS netsession_tourney_coin_ledger_kind_idx
  ON netsession_tourney_coin_ledger (kind);

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS coin_cost INTEGER NOT NULL DEFAULT 0;

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS coin_refund_policy TEXT NOT NULL DEFAULT 'until_tournament_end';

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS coin_charge_mode TEXT NOT NULL DEFAULT 'captain_only';
