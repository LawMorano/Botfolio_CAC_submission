-- Botfolio database schema
-- Applied by db.init_db(), which is called from seed.py.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS schema_migrations;
DROP TABLE IF EXISTS academy_lesson_progress;
DROP TABLE IF EXISTS pending_model_uploads;
DROP TABLE IF EXISTS security_incidents;
DROP TABLE IF EXISTS upload_attempts;
DROP TABLE IF EXISTS team_membership_requests;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS comment_reports;
DROP TABLE IF EXISTS comment_helpful;
DROP TABLE IF EXISTS design_of_week_awards;
DROP TABLE IF EXISTS design_of_week_history;
DROP TABLE IF EXISTS saved_designs;
DROP TABLE IF EXISTS design_contributors;
DROP TABLE IF EXISTS content_reports;
DROP TABLE IF EXISTS moderation_actions;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS featured_designs;
DROP TABLE IF EXISTS design_images;
DROP TABLE IF EXISTS resource_downloads;
DROP TABLE IF EXISTS design_resources;
DROP TABLE IF EXISTS design_relationships;
DROP TABLE IF EXISTS bom_items;
DROP TABLE IF EXISTS design_functions;
DROP TABLE IF EXISTS design_likes;
DROP TABLE IF EXISTS design_downloads;
DROP TABLE IF EXISTS design_view_state;
DROP TABLE IF EXISTS design_view_events;
DROP TABLE IF EXISTS design_visits;
DROP TABLE IF EXISTS tag_votes;
DROP TABLE IF EXISTS design_tags;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS ai_feedback;
DROP TABLE IF EXISTS designs;
DROP TABLE IF EXISTS archetypes;
DROP TABLE IF EXISTS seasons;
DROP TABLE IF EXISTS memberships;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS email_verification_tokens;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS retention_holds;
DROP TABLE IF EXISTS security_events;
DROP TABLE IF EXISTS users;


CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    bio           TEXT NOT NULL DEFAULT '',
    location      TEXT NOT NULL DEFAULT '',
    contact_email TEXT NOT NULL DEFAULT '',
    website_url   TEXT,
    social_links  TEXT NOT NULL DEFAULT '{}',
    profile_image TEXT,
    tagline       TEXT NOT NULL DEFAULT '',
    specialties   TEXT NOT NULL DEFAULT '',
    cad_tools     TEXT NOT NULL DEFAULT '',
    ftc_role      TEXT CHECK (ftc_role IN ('student', 'mentor', 'coach', 'affiliate')),
    interests     TEXT NOT NULL DEFAULT '',
    ftc_team_number INTEGER,
    founding_contributor_rank INTEGER UNIQUE,
    founding_contributor_at TEXT,
    onboarding_complete INTEGER NOT NULL DEFAULT 1 CHECK (onboarding_complete IN (0, 1)),
    accepted_terms_version TEXT,
    accepted_terms_at TEXT,
    accepted_privacy_version TEXT,
    accepted_privacy_at TEXT,
    acknowledged_legal_version TEXT,
    acknowledged_legal_at TEXT,
    age_13_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (age_13_confirmed IN (0, 1)),
    minor_permission_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (minor_permission_confirmed IN (0, 1)),
    registration_ip TEXT,
    email_verified_at TEXT,
    -- How email_verified_at came to be set. 'backfill' means a migration
    -- assumed it and nobody ever proved the address, so it must not be
    -- treated as inbox proof; NULL on an old row means the date predates
    -- this column and was genuine. Recorded rather than inferred: the
    -- inference it replaces read two columns that move independently, and
    -- acknowledging a legal update silently turned "never proven" into
    -- "proven".
    email_verified_source TEXT,
    -- Sign in with Google. google_sub is Google's stable account id and the
    -- only identity key the OAuth flow matches on; the email may change under
    -- it. No inline UNIQUE: the named index below is the single source of that
    -- constraint on fresh and upgraded databases alike.
    google_sub    TEXT,
    auth_provider TEXT NOT NULL DEFAULT 'password',
    suspended_at TEXT,
    suspended_until TEXT,
    banned_at TEXT,
    deleted_at TEXT,
    storage_limit_bytes BIGINT NOT NULL DEFAULT 1073741824,
    storage_used_bytes BIGINT NOT NULL DEFAULT 0,
    is_admin      INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
-- NULLs are distinct in a unique index on both SQLite and Postgres, so every
-- password-only account coexists here.
CREATE UNIQUE INDEX idx_users_google_sub ON users(google_sub);

CREATE TABLE academy_lesson_progress (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    course_slug TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, platform, course_slug, lesson_id)
);
CREATE INDEX idx_academy_progress_recent ON academy_lesson_progress(user_id, completed_at DESC);

CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO schema_migrations(version) VALUES (1);

CREATE TABLE user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);

CREATE TABLE security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    ip_address TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_security_events_occurred ON security_events(occurred_at);
CREATE INDEX idx_security_events_user ON security_events(user_id, occurred_at);

CREATE TABLE retention_holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    released_at TEXT
);
CREATE INDEX idx_retention_holds_target ON retention_holds(target_type,target_id,released_at,expires_at);


CREATE TABLE password_reset_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_reset_user ON password_reset_tokens(user_id);

CREATE TABLE email_verification_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_email_verification_user ON email_verification_tokens(user_id);


CREATE TABLE teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program     TEXT NOT NULL DEFAULT 'ftc',
    number      INTEGER NOT NULL,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL DEFAULT '',
    biography   TEXT NOT NULL DEFAULT '',
    profile_image TEXT,
    banner_image TEXT,
    website_url TEXT,
    social_links TEXT NOT NULL DEFAULT '{}',
    other_links TEXT NOT NULL DEFAULT '{}',
    is_founding INTEGER NOT NULL DEFAULT 0 CHECK (is_founding IN (0, 1)),
    founding_rank INTEGER UNIQUE,
    founding_qualified_at TEXT,
    profile_status TEXT NOT NULL DEFAULT 'claimed' CHECK (profile_status IN ('reference', 'claimed')),
    -- The first user to claim a team number owns it and holds the invite code.
    -- This proves "someone vouched for you", NOT that FIRST recognises you as
    -- a member. See the limitations section of the README.
    owner_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    invite_code TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (program, number)
);
CREATE UNIQUE INDEX idx_teams_program_number ON teams(program, number);


CREATE TABLE memberships (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    role      TEXT NOT NULL DEFAULT 'member',   -- 'owner' | 'member'
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, team_id)
);


CREATE TABLE seasons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    program    TEXT NOT NULL DEFAULT 'ftc',
    name       TEXT NOT NULL,            -- 'INTO THE DEEP'
    year_label TEXT NOT NULL,            -- '2024-25'
    slug       TEXT NOT NULL UNIQUE,     -- 'into-the-deep'
    sort_order INTEGER NOT NULL DEFAULT 0
);


-- Archetypes are community-coined and mostly season-specific: an archetype is a
-- robot's role/strategy and how it scores. season_id is nullable so that
-- cross-season mechanisms (e.g. "boxtube") aren't pinned to one game.
-- Users can coin new ones from the submit form; created_by records who did.
CREATE TABLE archetypes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id   INTEGER REFERENCES seasons(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (season_id, slug)
);


CREATE TABLE designs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id        INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    program        TEXT NOT NULL DEFAULT 'ftc',
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    onshape_link TEXT,
    cad_software TEXT,
    cad_link TEXT,
    season_id      INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    archetype_id   INTEGER REFERENCES archetypes(id) ON DELETE SET NULL,
    design_type TEXT NOT NULL DEFAULT 'other',
    replacement_cost_low_cents INTEGER,
    replacement_cost_high_cents INTEGER,
    replacement_cost_currency TEXT NOT NULL DEFAULT 'USD',
    prototype_version INTEGER CHECK (prototype_version BETWEEN 1 AND 99),
    competition_tested INTEGER NOT NULL DEFAULT 0 CHECK (competition_tested IN (0, 1)),
    length_in      REAL CHECK (length_in > 0),
    width_in       REAL CHECK (width_in > 0),
    height_in      REAL CHECK (height_in > 0),
    dimension_unit TEXT NOT NULL DEFAULT 'in' CHECK (dimension_unit IN ('in', 'mm')),
    motor_count    INTEGER CHECK (motor_count BETWEEN 0 AND 99),
    servo_count    INTEGER CHECK (servo_count BETWEEN 0 AND 99),
    -- The preview shown everywhere. Either a render captured from the 3D
    -- viewer or a plain uploaded photo — nothing downstream cares which.
    image_filename TEXT NOT NULL,
    model_filename TEXT,          -- .stl / .obj, if one was uploaded
    model_size_bytes BIGINT NOT NULL DEFAULT 0,
    model_sha256 TEXT,
    storage_bytes BIGINT NOT NULL DEFAULT 0,
    upload_status TEXT NOT NULL DEFAULT 'approved' CHECK (upload_status IN ('uploading','quarantined','approved','rejected','removed')),
    uploaded_by_admin INTEGER NOT NULL DEFAULT 0 CHECK (uploaded_by_admin IN (0, 1)),
    team_attribution_accepted INTEGER NOT NULL DEFAULT 1 CHECK (team_attribution_accepted IN (0, 1)),
    camera_json    TEXT,          -- viewer camera state, so "View in 3D"
    upload_certification_version TEXT,
    upload_certification_accepted INTEGER NOT NULL DEFAULT 0 CHECK (upload_certification_accepted IN (0, 1)),
    is_hidden INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0, 1)),
                                  -- reopens at the angle the author framed
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_designs_user    ON designs(user_id);
CREATE INDEX idx_designs_program ON designs(program);
CREATE INDEX idx_designs_season  ON designs(season_id);
CREATE INDEX idx_designs_created ON designs(created_at DESC);
CREATE INDEX idx_designs_cad_software ON designs(cad_software);

CREATE TABLE design_functions (
    design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    function_key TEXT NOT NULL,
    PRIMARY KEY (design_id, function_key)
);
CREATE INDEX idx_design_functions_key ON design_functions(function_key, design_id);

CREATE TABLE design_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    function_key TEXT,
    filename TEXT,
    original_filename TEXT,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sha256 TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_design_resources_design ON design_resources(design_id, position, id);

CREATE TABLE resource_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id INTEGER NOT NULL REFERENCES design_resources(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    visitor_key TEXT NOT NULL,
    downloaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_resource_downloads_resource ON resource_downloads(resource_id, downloaded_at);

CREATE TABLE design_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    target_design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_design_id, target_design_id, relationship_type)
);

CREATE TABLE bom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    part_name TEXT NOT NULL,
    part_number TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1,
    unit TEXT NOT NULL DEFAULT 'ea',
    unit_cost_cents INTEGER,
    product_url TEXT,
    notes TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_bom_items_design ON bom_items(design_id, position, id);

CREATE TABLE design_images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id  INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    filename   TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (design_id, position)
);
CREATE INDEX idx_design_images_design ON design_images(design_id, position);

CREATE TABLE featured_designs (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL CHECK (position BETWEEN 1 AND 6),
    PRIMARY KEY (user_id, design_id),
    UNIQUE (user_id, position)
);

CREATE TABLE comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id  INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id  INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    body       TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
    status     TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden','deleted')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_comments_design ON comments(design_id, created_at, id);
CREATE INDEX idx_comments_user ON comments(user_id, created_at DESC);

CREATE TABLE comment_helpful (comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (comment_id, user_id));
CREATE INDEX idx_comment_helpful_comment ON comment_helpful(comment_id);

CREATE TABLE comment_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id  INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    UNIQUE (comment_id, reporter_id)
);

CREATE TABLE saved_designs (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, design_id));
CREATE INDEX idx_saved_designs_user ON saved_designs(user_id, created_at DESC);
CREATE TABLE design_contributors (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT, credited_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (design_id, user_id));
CREATE INDEX idx_design_contributors_user ON design_contributors(user_id, credited_at DESC);
CREATE TABLE design_of_week_awards (design_id INTEGER PRIMARY KEY REFERENCES designs(id) ON DELETE CASCADE, selected_by INTEGER REFERENCES users(id) ON DELETE SET NULL, selected_at TEXT NOT NULL DEFAULT (datetime('now')), is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)), current_week TEXT);
CREATE TABLE design_of_week_history (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, week_start TEXT NOT NULL, selected_by INTEGER REFERENCES users(id) ON DELETE SET NULL, selected_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(design_id,week_start));
CREATE INDEX idx_design_of_week_history_week ON design_of_week_history(week_start,selected_at DESC);

CREATE TABLE team_membership_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    initiated_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('invitation','request')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','denied','cancelled')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    responded_at    TEXT
);
CREATE INDEX idx_team_membership_requests_user ON team_membership_requests(user_id,status,created_at DESC);
CREATE INDEX idx_team_membership_requests_team ON team_membership_requests(team_id,status,created_at DESC);

CREATE TABLE content_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    content_type TEXT NOT NULL,
    content_id TEXT,
    content_url TEXT NOT NULL,
    reason TEXT NOT NULL,
    description TEXT NOT NULL,
    reporter_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    workflow_status TEXT NOT NULL DEFAULT 'new' CHECK (workflow_status IN ('new','under_review','action_taken','closed')),
    assigned_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decision_reason TEXT NOT NULL DEFAULT '',
    urgent INTEGER NOT NULL DEFAULT 0 CHECK (urgent IN (0, 1)),
    priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 3),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    action_taken_at TEXT,
    resolved_at TEXT
);
CREATE INDEX idx_content_reports_status ON content_reports(status, urgent, created_at);
CREATE INDEX idx_content_reports_workflow ON content_reports(workflow_status, urgent, created_at);

CREATE TABLE moderation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE security_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_number TEXT NOT NULL UNIQUE,
    discovery_date TEXT NOT NULL,
    discovered_by TEXT NOT NULL,
    systems_affected TEXT NOT NULL,
    information_affected TEXT NOT NULL,
    actions_taken TEXT NOT NULL,
    credentials_rotated TEXT NOT NULL,
    vendors_contacted TEXT NOT NULL,
    notifications TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    corrective_action TEXT NOT NULL,
    resolution_date TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_security_incidents_dates ON security_incidents(resolution_date, discovery_date DESC);

CREATE TABLE notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    design_id  INTEGER REFERENCES designs(id) ON DELETE CASCADE,
    comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('comment','reply')),
    read_at    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_notifications_user ON notifications(user_id, read_at, created_at DESC);


CREATE TABLE ai_feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id   INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    requester_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    question    TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    rubric_json TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'ok',   -- 'ok' | 'unavailable' | 'error'
    saved_at    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_feedback_design ON ai_feedback(design_id, created_at DESC);
CREATE INDEX idx_feedback_requester ON ai_feedback(requester_id, saved_at, created_at DESC);
CREATE INDEX idx_feedback_expiry ON ai_feedback(saved_at, created_at);


-- `key` is the spelling-insensitive fingerprint two tags are folded on, so
-- "intake" and "Intakes" cannot become separate rows. Deployed databases pick
-- it up from the runtime migration in app.py; it belongs here too so a database
-- created from this file is usable without one.
CREATE TABLE tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    key        TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);


CREATE TABLE design_tags (
    design_id  INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    added_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    low_score_since TEXT,
    PRIMARY KEY (design_id, tag_id)
);


-- A vote answers "does this tag actually describe THIS robot?", so it is scoped
-- to the (design, tag) pair rather than to the tag globally. The composite
-- primary key is what enforces one vote per user per tag per design — the
-- database does that work, not the Python.
CREATE TABLE tag_votes (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    design_id  INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    value      INTEGER NOT NULL CHECK (value IN (-1, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, design_id, tag_id),
    FOREIGN KEY (design_id, tag_id)
        REFERENCES design_tags(design_id, tag_id) ON DELETE CASCADE
);

CREATE INDEX idx_votes_design_tag ON tag_votes(design_id, tag_id);

CREATE TABLE design_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, visitor_key TEXT NOT NULL, visited_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_design_visits ON design_visits(design_id, visitor_key, visited_at);
-- Clean view counter introduced on 2026-10-12. Events are retained forever;
-- the state table exists only to enforce the exact per-person cooldown.
CREATE TABLE design_view_events (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, viewed_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_design_view_events_design ON design_view_events(design_id, viewed_at);
CREATE TABLE design_view_state (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, visitor_key TEXT NOT NULL, last_viewed_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (design_id, visitor_key));
CREATE TABLE design_downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, visitor_key TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'file', downloaded_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_design_downloads_visitor ON design_downloads(design_id, visitor_key, downloaded_at);
CREATE INDEX idx_design_downloads_budget ON design_downloads(visitor_key, downloaded_at);
CREATE TABLE design_likes (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, design_id));
CREATE INDEX idx_design_likes_design ON design_likes(design_id);
CREATE TABLE upload_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_upload_attempts ON upload_attempts(user_id, created_at);

CREATE TABLE pending_model_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    object_filename TEXT NOT NULL UNIQUE,
    declared_size_bytes BIGINT NOT NULL,
    multipart_upload_id TEXT,
    upload_completed_at TEXT,
    promoted_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','rejected')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    consumed_at TEXT
);
CREATE INDEX idx_pending_model_uploads_user ON pending_model_uploads(user_id,status,expires_at);
