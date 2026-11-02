CREATE TABLE assistant_tickets (
 token_hash text PRIMARY KEY,
 session_id text NOT NULL REFERENCES auth_sessions(id),
 space_id text NOT NULL REFERENCES spaces(id),
 origin text NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '60 seconds'
);
CREATE TABLE assistant_sessions (
 token_hash text PRIMARY KEY,
 session_id text NOT NULL REFERENCES auth_sessions(id),
 space_id text NOT NULL REFERENCES spaces(id),
 origin text NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days'
);
CREATE INDEX ON assistant_sessions(session_id);
