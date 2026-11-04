-- Upstream BYCEPS 8fc0d8a91 (2026-09-30) "Allow ticket user to specify source of chair"
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS chair_source text;
