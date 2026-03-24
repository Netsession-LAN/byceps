ALTER TABLE netsession_tourney_sponsor_logo_assets
  ADD COLUMN IF NOT EXISTS target_url TEXT;
