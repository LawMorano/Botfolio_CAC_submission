import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class PhaseOneCommunityTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        self.owner_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,email_verified_at) VALUES ('owner','owner@example.com','hash',1,datetime('now'))"
        ).lastrowid
        self.contributor_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,email_verified_at) VALUES ('contributor','contributor@example.com','hash',1,datetime('now'))"
        ).lastrowid
        self.team_id = conn.execute(
            "INSERT INTO teams(number,name,biography,owner_id,invite_code) VALUES (9581,'Techno Tigers','A completed team profile',?,'invite')",
            (self.owner_id,),
        ).lastrowid
        self.design_id = conn.execute(
            """INSERT INTO designs(user_id,team_id,title,description,image_filename,prototype_version,
                       competition_tested,length_in,width_in,height_in,upload_status)
                 VALUES (?,?,'Intake','Competition intake','preview.jpg',1,1,18,18,12,'approved')""",
            (self.owner_id, self.team_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_images(design_id,filename,position) VALUES (?,'preview.jpg',0)",
            (self.design_id,),
        )
        self.comment_id = conn.execute(
            "INSERT INTO comments(design_id,user_id,body) VALUES (?,?,'Try a softer wheel')",
            (self.design_id, self.owner_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"

    def test_team_design_qualifies_team_but_credit_alone_does_not_qualify_contributor(self):
        conn = db.connect()
        self.assertTrue(self.application.qualify_founding_team(conn, self.team_id))
        self.application.save_design_contributors(
            conn, self.design_id, ["contributor"], ["Programming"]
        )
        conn.commit()
        team = conn.execute("SELECT founding_rank FROM teams WHERE id=?", (self.team_id,)).fetchone()
        person = conn.execute(
            "SELECT founding_contributor_rank FROM users WHERE id=?", (self.contributor_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(team["founding_rank"], 1)
        self.assertIsNone(person["founding_contributor_rank"])

    def test_named_team_does_not_need_biography_to_qualify(self):
        conn = db.connect()
        conn.execute("UPDATE teams SET biography='' WHERE id=?", (self.team_id,))
        self.assertTrue(self.application.qualify_founding_team(conn, self.team_id))
        conn.close()

    def test_admin_only_empty_team_is_migrated_to_reference_and_loses_founder_rank(self):
        conn = db.connect()
        reference_id = conn.execute(
            "INSERT INTO teams(number,name,invite_code,is_founding,founding_rank) "
            "VALUES (8675,'Seattle Solvers','reference',1,1)"
        ).lastrowid
        conn.execute(
            """INSERT INTO designs(user_id,team_id,title,description,image_filename,
                      prototype_version,competition_tested,length_in,width_in,height_in,
                      upload_status,uploaded_by_admin)
                 VALUES (?,?,'Seattle Solvers Robot','Admin credit','seattle.jpg',
                         1,0,18,18,18,'approved',1)""",
            (self.owner_id, reference_id),
        )
        self.application._migrate_team_references(conn)
        team = conn.execute(
            "SELECT profile_status,founding_rank FROM teams WHERE id=?", (reference_id,)
        ).fetchone()
        design = conn.execute(
            "SELECT team_attribution_accepted FROM designs WHERE team_id=?", (reference_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(team["profile_status"], "reference")
        self.assertIsNone(team["founding_rank"])
        self.assertEqual(design["team_attribution_accepted"], 0)

    def test_uploader_qualifies_as_founding_contributor(self):
        conn = db.connect()
        self.assertTrue(self.application.qualify_founding_contributor(conn, self.owner_id))
        owner = conn.execute(
            "SELECT founding_contributor_rank FROM users WHERE id=?", (self.owner_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(owner["founding_contributor_rank"], 1)

    def test_ai_feedback_is_private_and_saved_chats_only_appear_on_owners_profile(self):
        conn = db.connect()
        owner_chat = conn.execute(
            """INSERT INTO ai_feedback(design_id,requester_id,question,rubric_json,summary,status)
                 VALUES (?,?,?,?,'Owner summary','ok')""",
            (self.design_id, self.owner_id, "Owner private question",
             '{"summary":"Owner private response","answer":"Owner-only answer"}'),
        ).lastrowid
        conn.execute(
            """INSERT INTO ai_feedback(design_id,requester_id,question,rubric_json,summary,status)
                 VALUES (?,?,?,?,'Contributor summary','ok')""",
            (self.design_id, self.contributor_id, "Contributor private question",
             '{"summary":"Contributor private response","answer":"Contributor-only answer"}'),
        )
        conn.commit()
        conn.close()

        anonymous = self.client.get(f"/designs/{self.design_id}")
        self.assertNotIn(b"Owner-only answer", anonymous.data)
        self.assertNotIn(b"Contributor-only answer", anonymous.data)

        self.login(self.owner_id)
        owner_page = self.client.get(f"/designs/{self.design_id}")
        self.assertIn(b"Owner-only answer", owner_page.data)
        self.assertNotIn(b"Contributor-only answer", owner_page.data)
        saved = self.client.post(
            f"/ai-chats/{owner_chat}/save", data={"csrf_token": "test-csrf"}
        )
        self.assertEqual(saved.status_code, 302)
        owner_profile = self.client.get("/u/owner")
        self.assertIn(b"Owner private question", owner_profile.data)
        self.assertIn(b"Owner-only answer", owner_profile.data)

        self.login(self.contributor_id)
        contributor_page = self.client.get(f"/designs/{self.design_id}")
        self.assertIn(b"Contributor-only answer", contributor_page.data)
        self.assertNotIn(b"Owner-only answer", contributor_page.data)
        other_profile = self.client.get("/u/owner")
        self.assertNotIn(b"Owner private question", other_profile.data)
        forbidden_save = self.client.post(
            f"/ai-chats/{owner_chat}/save", data={"csrf_token": "test-csrf"}
        )
        self.assertEqual(forbidden_save.status_code, 404)

    def test_profile_collapses_designs_after_the_first_nine(self):
        conn = db.connect()
        for number in range(2, 11):
            conn.execute(
                """INSERT INTO designs(user_id,title,description,image_filename,upload_status)
                     VALUES (?,?,?,?, 'approved')""",
                (self.owner_id, f"Design {number}", "Profile contribution", "preview.jpg"),
            )
        conn.commit()
        conn.close()

        html = self.client.get("/u/owner").get_data(as_text=True)
        first_grid, collapsed = html.split('<details class="profile-designs-more">', 1)

        self.assertEqual(first_grid.count('class="card design-card"'), 9)
        self.assertEqual(collapsed.count('class="card design-card"'), 1)
        self.assertIn('>See all <span aria-hidden="true">&rarr;</span></summary>', collapsed)

    def test_empty_bom_and_subsystems_are_hidden_from_design_visitors(self):
        conn = db.connect()
        conn.execute(
            "UPDATE designs SET replacement_cost_low_cents=200000, "
            "replacement_cost_high_cents=350000 WHERE id=?",
            (self.design_id,),
        )
        conn.commit()
        conn.close()

        html = self.client.get(f"/designs/{self.design_id}").get_data(as_text=True)

        self.assertIn("Engineering Resources", html)
        self.assertIn("Estimated replacement cost", html)
        self.assertNotIn('id="subsystems"', html)
        self.assertNotIn('id="bom"', html)
        self.assertNotIn('href="#subsystems"', html)
        self.assertNotIn('href="#bom"', html)
        self.assertNotIn("<span>Subsystems</span>", html)
        self.assertNotIn("<span>BOM items</span>", html)

    def test_download_library_lists_downloaded_designs_privately(self):
        conn = db.connect()
        drivetrain_id = conn.execute(
            """INSERT INTO designs(user_id,title,description,image_filename,upload_status)
                 VALUES (?,'Drivetrain','Six-wheel drive','preview.jpg','approved')""",
            (self.contributor_id,),
        ).lastrowid
        hidden_id = conn.execute(
            """INSERT INTO designs(user_id,title,description,image_filename,upload_status,is_hidden)
                 VALUES (?,'HiddenSecret','Moderated design','preview.jpg','approved',1)""",
            (self.contributor_id,),
        ).lastrowid
        # Owner downloaded the drivetrain twice (dedupes to one card, ordered by
        # the latest) and the intake once, earlier. Also a download of a hidden
        # design (must be excluded) and a contributor's download of the intake
        # (must not leak into the owner's library).
        conn.executemany(
            "INSERT INTO design_downloads(design_id,user_id,downloaded_at) VALUES (?,?,?)",
            [
                (self.design_id, self.owner_id, "2026-01-01 00:00:00"),
                (drivetrain_id, self.owner_id, "2026-01-15 00:00:00"),
                (drivetrain_id, self.owner_id, "2026-02-01 00:00:00"),
                (hidden_id, self.owner_id, "2026-02-02 00:00:00"),
                (self.design_id, self.contributor_id, "2026-02-03 00:00:00"),
            ],
        )
        conn.commit()
        conn.close()

        self.login(self.owner_id)
        page = self.client.get("/library")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Download Library", html)
        # Badge counts two distinct, visible designs (repeat + hidden excluded).
        self.assertIn("<a href=\"#downloads\">Downloads <span>2</span></a>", html)

        section = html[html.index('id="downloads"'):]
        self.assertIn("Drivetrain", section)
        self.assertIn("Intake", section)
        self.assertNotIn("HiddenSecret", section)
        # One card per design even though the drivetrain was downloaded twice.
        self.assertEqual(section.count('href="/designs/%d"' % drivetrain_id), 1)
        # Most recently downloaded first: drivetrain (Feb) before intake (Jan).
        self.assertLess(section.index("Drivetrain"), section.index("Intake"))

        # Libraries are strictly per-account: /library only ever shows the
        # signed-in viewer's own history, so the contributor sees the intake
        # they downloaded but never the drivetrain only the owner took.
        self.login(self.contributor_id)
        other = self.client.get("/library").get_data(as_text=True)
        other_downloads = other[other.index('id="downloads"'):]
        self.assertIn("Intake", other_downloads)
        self.assertNotIn("Drivetrain", other_downloads)

    def test_my_library_is_reachable_from_the_account_menu_and_gated(self):
        # Signed out, the private library redirects to sign-in rather than 404 or
        # leaking; signed in, the top-bar account menu links straight to it.
        signed_out = self.client.get("/library")
        self.assertEqual(signed_out.status_code, 302)
        self.assertIn("/login", signed_out.headers["Location"])

        self.login(self.owner_id)
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/library"', home)
        self.assertIn("My Library", home)
        library = self.client.get("/library")
        self.assertEqual(library.status_code, 200)
        self.assertIn("My Library", library.get_data(as_text=True))

    def test_design_detail_actions_have_separate_layout_hooks(self):
        template = (Path(__file__).parents[1] / "templates" / "design_detail.html").read_text(
            encoding="utf-8"
        )
        stylesheet = (Path(__file__).parents[1] / "static" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("detail-card__award", template)
        self.assertIn("design-admin-award", template)
        self.assertIn(".detail-card__award", stylesheet)
        self.assertIn(".design-admin-award", stylesheet)

    def test_about_link_is_on_home_page_not_header(self):
        root = Path(__file__).parents[1]
        base = (root / "templates" / "base.html").read_text(encoding="utf-8")
        home = (root / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('<a href="{{ url_for(\'about\') }}">About</a>', base)
        self.assertIn('href="{{ url_for(\'about\') }}">Learn about Botfolio</a>', home)

    def test_home_page_shows_twelve_newest_designs_by_publish_time(self):
        # The homepage's "Newest designs" section must be chronological; the
        # gallery's curated shelf buckets must not move older designs ahead.
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        index_query = source[source.index("def index():"):source.index("@app.route(\"/founding-50\")")]
        newest_query = index_query[index_query.index("designs = conn.execute"):index_query.index("total = conn.execute")]
        self.assertNotIn("DESIGN_SHELF_ORDER", newest_query)
        self.assertIn("ORDER BY d.created_at DESC, d.id DESC", newest_query)
        self.assertIn("LIMIT 12", index_query)

    def test_home_hero_ranking_is_award_based_and_postgres_safe(self):
        # The hero carousel shows only the designs awarded Design of the Week,
        # ranked by award recency. It must never rank by reusing the SELECT-list
        # aggregate aliases in ORDER BY, which is what broke on Postgres.
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        index_query = source[source.index("def index():"):source.index("@app.route(\"/founding-50\")")]
        hero_query = index_query[index_query.index("hero_slides"):]
        self.assertNotIn("like_count * 3 + download_count * 2 + visit_count", index_query)
        self.assertIn("JOIN design_of_week_awards dw ON dw.design_id=d.id", hero_query)
        self.assertIn("ORDER BY dw.selected_at DESC", hero_query)

    def test_home_hero_previews_the_week_as_a_merry_go_round_coverflow(self):
        root = Path(__file__).parents[1]
        home = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "dotw-carousel.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "style.css").read_text(encoding="utf-8")
        # The week's designs preview at the top, inside the hero, as a coverflow.
        hero = home[home.index('<section class="hero">'):home.index("</section>")]
        self.assertIn("hero__preview dotw", hero)
        self.assertIn("data-dotw-carousel", hero)
        self.assertIn("for d in hero_slides", hero)
        # Three seats on the ring: a sharp centre and two blurred, angled neighbours.
        self.assertIn("seatOf", script)
        for seat in ("is-center", "is-left", "is-right", "is-back"):
            self.assertIn(seat, script)
        self.assertIn(".dotw-card.is-center", stylesheet)
        self.assertIn("blur(5px)", stylesheet)
        self.assertIn("perspective: 1600px", stylesheet)

    def test_home_layout_features_four_weekly_winners_without_founding_50_ad(self):
        root = Path(__file__).parents[1]
        home = (root / "templates" / "index.html").read_text(encoding="utf-8")
        base = (root / "templates" / "base.html").read_text(encoding="utf-8")
        source = (root / "app.py").read_text(encoding="utf-8")
        self.assertLess(home.index("home-featured"), home.index("home-newest"))
        self.assertIn("for d in designs_of_week", home)
        self.assertIn("ORDER BY dw.selected_at DESC LIMIT 4", source)
        self.assertNotIn("Founding 50", home)
        self.assertNotIn('class="topbar__founding"', base)
        self.assertIn('class="founding-team-badge"', (root / "templates" / "team.html").read_text(encoding="utf-8"))

    def test_founding_50_has_premium_gold_treatment_and_first_visit_confetti(self):
        root = Path(__file__).parents[1]
        page = (root / "templates" / "founding_50.html").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn('class="founding-premium"', page)
        self.assertIn("botfolio-founding-50-celebrated", page)
        self.assertIn("prefers-reduced-motion: reduce", page)
        self.assertIn(".founding-premium", stylesheet)
        self.assertIn("@keyframes founding-confetti-fall", stylesheet)

    def test_save_helpful_and_weekly_award_routes(self):
        self.login(self.contributor_id)
        self.assertEqual(
            self.client.post(f"/designs/{self.design_id}/save", data={"csrf_token": "test-csrf"}).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(f"/comments/{self.comment_id}/helpful", data={"csrf_token": "test-csrf"}).status_code,
            302,
        )
        conn = db.connect()
        self.assertIsNotNone(conn.execute("SELECT 1 FROM saved_designs").fetchone())
        self.assertIsNotNone(conn.execute("SELECT 1 FROM comment_helpful").fetchone())
        conn.close()

    def test_design_and_robotics_profiles_render(self):
        conn = db.connect()
        self.application.save_design_contributors(
            conn, self.design_id, ["contributor"], ["Programming"]
        )
        conn.commit()
        conn.close()
        self.login(self.contributor_id)
        self.assertEqual(self.client.get(f"/designs/{self.design_id}").status_code, 200)
        self.assertEqual(self.client.get("/u/contributor").status_code, 200)
        self.assertEqual(self.client.get("/founding-50").status_code, 200)


if __name__ == "__main__":
    unittest.main()
