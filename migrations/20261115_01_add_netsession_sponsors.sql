-- Netsession sponsors module (ADR 0005). Keep in sync with
-- byceps/services/netsession_sponsor/dbmodels.py.
CREATE TABLE IF NOT EXISTS netsession_sponsors (
  id UUID PRIMARY KEY,
  party_id TEXT NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  logo_path TEXT NOT NULL,
  logo_dark_path TEXT,
  target_url TEXT,
  position INTEGER NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_netsession_sponsors_party_id
  ON netsession_sponsors (party_id);

-- Take over the partners hard-coded in the homepage template until now
-- (logos stay where they are), for the current party of site `netsession`,
-- only if that party has no sponsors yet.
INSERT INTO netsession_sponsors
  (id, party_id, name, logo_path, target_url, position, enabled, created_at, updated_at)
SELECT gen_random_uuid(), s.party_id, v.name,
       'parties/netsession-2025/sponsors/' || v.file, v.url, v.position, TRUE,
       now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
FROM sites s
CROSS JOIN (VALUES
  (1, 'Koenig Consulting', 'Koenig.svg', 'https://koenig-consulting.de/'),
  (2, 'Shirtinator', 'Shirtinator.png', 'https://www.shirtinator.de/'),
  (3, 'Hetzner', 'Hetzner.svg', 'https://www.hetzner.com/de?mtm_campaign=netsession_sponsoring&mtm_medium=referral&mtm_content=sponsoring_link'),
  (4, 'Axis', 'Axis.svg', 'https://www.axis.com/de-de'),
  (5, 'Volt', 'Volt.svg', 'https://www.voltcola.de/'),
  (6, 'be quiet!', 'Be-quiet.svg', 'https://www.bequiet.com/de'),
  (7, 'MonacoKeys', 'MonacoKeys.svg', 'https://monacokeys.de/'),
  (8, '1337 Camp', '1337camp.svg', 'https://1337.camp/de'),
  (9, 'Spezi', 'Spezi.svg', 'https://www.spezi.com/spezi-energy'),
  (10, 'Thermal Grizzly', 'Thermal-Grizzly.svg', 'https://www.thermal-grizzly.com/')
) AS v(position, name, file, url)
WHERE s.id = 'netsession'
  AND s.party_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM netsession_sponsors x WHERE x.party_id = s.party_id
  );
