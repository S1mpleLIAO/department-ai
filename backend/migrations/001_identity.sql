-- Explicit migration only: existing content remains quarantined until assigned.
CREATE TABLE companies (id text PRIMARY KEY, name text NOT NULL UNIQUE);
INSERT INTO companies VALUES ('zkxk','中科信控'),('senyuan','森远股份');
CREATE TABLE spaces (
 id text PRIMARY KEY, name text NOT NULL, kind text NOT NULL CHECK(kind IN ('company','shared','legacy')),
 company_id text REFERENCES companies(id),
 CHECK ((kind='company') = (company_id IS NOT NULL))
);
INSERT INTO spaces VALUES ('zkxk','中科信控','company','zkxk'),('senyuan','森远股份','company','senyuan'),
 ('shared','部门共享','shared',NULL),('legacy','待确认历史资料','legacy',NULL);
CREATE TABLE users (
 id text PRIMARY KEY, username text NOT NULL UNIQUE, display_name text NOT NULL,
 password_hash text NOT NULL, company_id text NOT NULL REFERENCES companies(id),
 active boolean NOT NULL DEFAULT true, superadmin boolean NOT NULL DEFAULT false,
 must_change_password boolean NOT NULL DEFAULT true, permission_version integer NOT NULL DEFAULT 1,
 revision integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE permission_groups (
 id text PRIMARY KEY, name text NOT NULL UNIQUE, description text NOT NULL DEFAULT '',
 actions jsonb NOT NULL CHECK(jsonb_typeof(actions)='array'), revision integer NOT NULL DEFAULT 1
);
CREATE TABLE user_space_grants (
 user_id text REFERENCES users(id), group_id text REFERENCES permission_groups(id),
 space_id text REFERENCES spaces(id), PRIMARY KEY(user_id,group_id,space_id),
 CHECK(space_id <> 'legacy')
);
CREATE TABLE auth_sessions (
 id text PRIMARY KEY, token_hash text NOT NULL UNIQUE, csrf text NOT NULL,
 user_id text NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 last_seen_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 revoked_at timestamptz, user_agent text NOT NULL DEFAULT ''
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);
CREATE TABLE auth_attempts (username_hash text NOT NULL, ip_hash text NOT NULL, attempted_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX auth_attempts_time ON auth_attempts(attempted_at);
CREATE TABLE audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id text REFERENCES users(id),
 action text NOT NULL, target_id text NOT NULL DEFAULT '', space_id text,
 created_at timestamptz NOT NULL DEFAULT now(), details jsonb NOT NULL DEFAULT '{}'
);
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['business_processes','process_steps','knowledge_categories','knowledge_purposes','knowledge_documents','knowledge_chunks']
 LOOP
  EXECUTE format('ALTER TABLE %I ADD COLUMN space_id text NOT NULL DEFAULT %L REFERENCES spaces(id)',t,'legacy');
  EXECUTE format('ALTER TABLE %I ALTER COLUMN space_id SET DEFAULT current_setting(%L,true)',t,'department.space');
  EXECUTE format('ALTER TABLE %I ADD COLUMN owner_id text REFERENCES users(id) DEFAULT nullif(current_setting(%L,true),%L)',t,'department.user','');
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY scoped_access ON %I USING (space_id=current_setting(%L,true)) WITH CHECK (space_id=current_setting(%L,true))',t,'department.space','department.space');
  EXECUTE format('CREATE INDEX ON %I(space_id)',t);
 END LOOP;
END $$;
ALTER TABLE business_processes ADD CONSTRAINT process_space_unique UNIQUE(space_id,id);
ALTER TABLE business_processes ADD COLUMN archived boolean NOT NULL DEFAULT false;
ALTER TABLE knowledge_categories ADD CONSTRAINT category_space_unique UNIQUE(space_id,id);
ALTER TABLE knowledge_documents ADD CONSTRAINT document_space_unique UNIQUE(space_id,id);
ALTER TABLE knowledge_chunks ADD CONSTRAINT chunk_document_space_unique UNIQUE(space_id,document_id,id);
ALTER TABLE knowledge_documents DROP CONSTRAINT knowledge_documents_purpose_id_fkey;
ALTER TABLE knowledge_purposes DROP CONSTRAINT knowledge_purposes_pkey;
ALTER TABLE knowledge_purposes ADD PRIMARY KEY(space_id,id);
ALTER TABLE knowledge_purposes DROP CONSTRAINT knowledge_purposes_name_key;
ALTER TABLE knowledge_purposes ADD UNIQUE(space_id,name);
DROP INDEX knowledge_categories_sibling_name;
CREATE UNIQUE INDEX knowledge_categories_sibling_name ON knowledge_categories(space_id,COALESCE(parent_id,''),name);
ALTER TABLE knowledge_categories ADD FOREIGN KEY(space_id,parent_id) REFERENCES knowledge_categories(space_id,id);
ALTER TABLE process_steps ADD FOREIGN KEY(space_id,process_id) REFERENCES business_processes(space_id,id) ON DELETE CASCADE;
ALTER TABLE knowledge_documents ADD FOREIGN KEY(space_id,category_id) REFERENCES knowledge_categories(space_id,id);
ALTER TABLE knowledge_documents ADD FOREIGN KEY(space_id,purpose_id) REFERENCES knowledge_purposes(space_id,id);
ALTER TABLE knowledge_chunks ADD FOREIGN KEY(space_id,document_id) REFERENCES knowledge_documents(space_id,id) ON DELETE CASCADE;
ALTER TABLE knowledge_chunks ADD FOREIGN KEY(space_id,document_id,parent_chunk_id) REFERENCES knowledge_chunks(space_id,document_id,id) DEFERRABLE INITIALLY DEFERRED;

