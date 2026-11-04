CREATE TABLE IF NOT EXISTS netsession_tourney_tournament_rule_templates (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id),
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  body_format TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  UNIQUE (party_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_tournament_rule_templates_party_id
  ON netsession_tourney_tournament_rule_templates (party_id);

