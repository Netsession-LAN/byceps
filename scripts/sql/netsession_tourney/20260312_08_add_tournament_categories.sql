CREATE TABLE IF NOT EXISTS netsession_tourney_tournament_categories (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id),
  position INTEGER NOT NULL,
  title TEXT NOT NULL,
  UNIQUE (party_id, title)
);

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_tournament_categories_party_id
  ON netsession_tourney_tournament_categories (party_id);

ALTER TABLE netsession_tourney_tournaments
  ADD COLUMN IF NOT EXISTS category_id UUID;

INSERT INTO netsession_tourney_tournament_categories (id, party_id, position, title)
SELECT
  (
    substr(t.category_hash, 1, 8)
    || '-'
    || substr(t.category_hash, 9, 4)
    || '-'
    || substr(t.category_hash, 13, 4)
    || '-'
    || substr(t.category_hash, 17, 4)
    || '-'
    || substr(t.category_hash, 21, 12)
  )::uuid AS id,
  t.party_id,
  1 AS position,
  'Allgemein' AS title
FROM (
  SELECT
    DISTINCT party_id,
    md5(party_id || ':netsession_tourney:default_category') AS category_hash
  FROM netsession_tourney_tournaments
) AS t
WHERE NOT EXISTS (
  SELECT 1
  FROM netsession_tourney_tournament_categories c
  WHERE c.party_id = t.party_id
);

UPDATE netsession_tourney_tournaments t
SET category_id = c.category_id
FROM (
  SELECT DISTINCT ON (party_id)
    party_id,
    id AS category_id
  FROM netsession_tourney_tournament_categories
  ORDER BY party_id, position ASC, id ASC
) AS c
WHERE t.party_id = c.party_id
  AND t.category_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_netsession_tourney_tournaments_category_id
  ON netsession_tourney_tournaments (category_id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'netsession_tourney_tournaments_category_id_fkey'
  ) THEN
    ALTER TABLE netsession_tourney_tournaments
      ADD CONSTRAINT netsession_tourney_tournaments_category_id_fkey
      FOREIGN KEY (category_id)
      REFERENCES netsession_tourney_tournament_categories (id);
  END IF;
END
$$;

ALTER TABLE netsession_tourney_tournaments
  ALTER COLUMN category_id SET NOT NULL;
