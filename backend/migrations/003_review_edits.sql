ALTER TABLE review_submissions ADD COLUMN target_id text;
ALTER TABLE review_submissions ADD COLUMN base_token text;
ALTER TABLE review_submissions ADD COLUMN base_payload jsonb;
ALTER TABLE review_submissions ADD CONSTRAINT review_edit_base
 CHECK ((target_id IS NULL AND base_token IS NULL AND base_payload IS NULL)
 OR (target_id IS NOT NULL AND base_token IS NOT NULL AND base_payload IS NOT NULL));
ALTER TABLE review_versions ADD COLUMN base_payload jsonb;
ALTER TABLE review_versions ADD COLUMN base_token text;
ALTER TABLE review_versions ADD COLUMN target_id text;
