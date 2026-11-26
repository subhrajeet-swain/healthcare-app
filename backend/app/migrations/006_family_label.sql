-- The manager's own name for a family member, encrypted with the tenant key. The manager's views
-- show only this, never the member's stored name (which lab staff may have entered).
ALTER TABLE family_links ADD COLUMN label_enc bytea;
