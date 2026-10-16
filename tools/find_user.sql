-- Find an account that the obvious lookups cannot see.
--
-- schema.sql declares username and email `UNIQUE COLLATE NOCASE`. SQLite honours
-- that for lookups as well as for uniqueness; Postgres has no NOCASE, so
-- infra/database.py strips it and restores only the uniqueness half, as unique
-- indexes on lower(username) and lower(email). A hand-written
-- `WHERE email = 'friend@gmail.com'` therefore misses an account stored as
-- "Friend@Gmail.com" -- while that account still owns the address and still
-- blocks a second signup. Same for a Gmail address written with or without dots.
--
-- Edit the two values in `wanted` below, then run the whole file:
--     psql "$DATABASE_URL" -f tools/find_user.sql
-- or paste it into Railway -> Postgres -> Data -> Query. Either value may be
-- left as '' if you only know the other one.

WITH wanted AS (
    SELECT lower(btrim('friend@gmail.com')) AS email,
           lower(btrim('their_username'))   AS username
),
-- Gmail delivers first.last@, firstlast@, firstlast+ftc@ and @googlemail.com to
-- one inbox. They are four different strings in this table.
wanted_inbox AS (
    SELECT regexp_replace(replace(split_part(email, '@', 1), '.', ''), '\+.*$', '') AS mailbox,
           split_part(email, '@', 2) AS domain
    FROM wanted
),
folded AS (
    SELECT u.id, u.username, u.email, u.created_at, u.email_verified_at,
           u.suspended_at, u.banned_at, u.deleted_at, u.onboarding_complete,
           lower(btrim(u.email))    AS email_folded,
           lower(btrim(u.username)) AS username_folded,
           regexp_replace(
               replace(split_part(lower(btrim(u.email)), '@', 1), '.', ''),
               '\+.*$', '') AS mailbox,
           split_part(lower(btrim(u.email)), '@', 2) AS domain
    FROM users u
)
SELECT f.id,
       f.username,
       f.email,
       f.created_at,
       CASE
           WHEN f.deleted_at   IS NOT NULL THEN 'deleted '   || f.deleted_at
           WHEN f.banned_at    IS NOT NULL THEN 'banned '    || f.banned_at
           WHEN f.suspended_at IS NOT NULL THEN 'suspended ' || f.suspended_at
           WHEN f.email_verified_at IS NULL THEN 'email never verified'
           WHEN f.onboarding_complete = 0   THEN 'onboarding unfinished'
           ELSE 'active'
       END AS account_state,
       array_to_string(array_remove(ARRAY[
           CASE WHEN f.email_folded = w.email AND w.email <> ''
                THEN 'email matches apart from capitals' END,
           CASE WHEN f.username_folded = w.username AND w.username <> ''
                THEN 'username matches apart from capitals' END,
           CASE WHEN f.mailbox = i.mailbox
                     AND f.domain IN ('gmail.com', 'googlemail.com')
                     AND i.domain IN ('gmail.com', 'googlemail.com')
                     AND f.email_folded <> w.email
                THEN 'same gmail inbox, written differently' END,
           CASE WHEN i.mailbox <> '' AND position(i.mailbox in f.email_folded) > 0
                     AND f.email_folded <> w.email
                THEN 'address contains the same mailbox name' END,
           CASE WHEN w.username <> '' AND position(w.username in f.username_folded) > 0
                     AND f.username_folded <> w.username
                THEN 'username contains what you searched for' END,
           CASE WHEN length(f.email) <> octet_length(f.email)
                THEN 'WARNING: address holds non-ASCII characters' END,
           CASE WHEN f.email <> btrim(f.email)
                THEN 'WARNING: address has leading or trailing whitespace' END
       ]::text[], NULL), '; ') AS why
FROM folded f
CROSS JOIN wanted w
CROSS JOIN wanted_inbox i
WHERE (w.email    <> '' AND f.email_folded    = w.email)
   OR (w.username <> '' AND f.username_folded = w.username)
   OR (i.mailbox  <> '' AND f.mailbox = i.mailbox
       AND f.domain IN ('gmail.com', 'googlemail.com')
       AND i.domain IN ('gmail.com', 'googlemail.com'))
   OR (i.mailbox  <> '' AND position(i.mailbox in f.email_folded) > 0)
   OR (w.username <> '' AND position(w.username in f.username_folded) > 0)
ORDER BY f.id;
