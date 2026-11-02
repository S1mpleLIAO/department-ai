CREATE TABLE review_submissions (
 id text PRIMARY KEY,
 space_id text NOT NULL REFERENCES spaces(id) DEFAULT current_setting('department.space',true),
 owner_id text NOT NULL REFERENCES users(id) DEFAULT current_setting('department.user',true),
 kind text NOT NULL CHECK(kind IN ('processes','knowledge','skills')),
 title text NOT NULL, draft jsonb NOT NULL,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','submitted','rejected','approved','publish_failed','published')),
 revision integer NOT NULL DEFAULT 1, version integer NOT NULL DEFAULT 0,
 feedback text NOT NULL DEFAULT '', publish_error text NOT NULL DEFAULT '',
 approved_by text REFERENCES users(id), published_id text,
 source_key text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(space_id,id), UNIQUE(space_id,owner_id,source_key)
);
CREATE TABLE review_versions (
 submission_id text NOT NULL, space_id text NOT NULL DEFAULT current_setting('department.space',true),
 number integer NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(submission_id,number),
 FOREIGN KEY(space_id,submission_id) REFERENCES review_submissions(space_id,id)
);
CREATE TABLE review_sources (
 submission_id text PRIMARY KEY, space_id text NOT NULL DEFAULT current_setting('department.space',true),
 name text NOT NULL, mime text NOT NULL, body bytea NOT NULL,
 FOREIGN KEY(space_id,submission_id) REFERENCES review_submissions(space_id,id)
);
CREATE TABLE skill_publications (
 id text NOT NULL, space_id text NOT NULL DEFAULT current_setting('department.space',true),
 submission_id text NOT NULL REFERENCES review_submissions(id),
 data jsonb NOT NULL, enabled boolean NOT NULL DEFAULT true, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(space_id,id)
);
ALTER TABLE review_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_submissions FORCE ROW LEVEL SECURITY;
CREATE POLICY review_scope ON review_submissions USING (
 space_id=current_setting('department.space',true) AND
 (owner_id=current_setting('department.user',true) OR
 kind=ANY(string_to_array(current_setting('department.review_kinds',true),',')))
) WITH CHECK (
 space_id=current_setting('department.space',true) AND
 (owner_id=current_setting('department.user',true) OR
 kind=ANY(string_to_array(current_setting('department.review_kinds',true),',')))
);
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['review_versions','review_sources'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY review_scope ON %I USING (space_id=current_setting(''department.space'',true) AND EXISTS(SELECT 1 FROM review_submissions s WHERE s.id=submission_id))',t);
 END LOOP;
END $$;
ALTER TABLE skill_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_publications FORCE ROW LEVEL SECURITY;
CREATE POLICY publication_scope ON skill_publications USING(space_id=current_setting('department.space',true));
CREATE INDEX review_list ON review_submissions(space_id,updated_at DESC);
CREATE FUNCTION immutable_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Submitted content is immutable'; END $$;
CREATE TRIGGER immutable_version BEFORE UPDATE OR DELETE ON review_versions FOR EACH ROW EXECUTE FUNCTION immutable_review();
CREATE TRIGGER immutable_source BEFORE UPDATE OR DELETE ON review_sources FOR EACH ROW EXECUTE FUNCTION immutable_review();
