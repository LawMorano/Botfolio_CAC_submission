import unittest
import urllib.error

from robotics import ftc_teams


_SAMPLE = {
    "number": 16405,
    "name": "Federal Bot Institute",
    "schoolName": "Renner Middle School",
    "city": "Plano",
    "state": "TX",
    "country": "USA",
    "rookieYear": 2019,
    "website": "",
}


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


class FtcTeamsTests(unittest.TestCase):
    def setUp(self):
        ftc_teams._cache.clear()
        self._orig_fetch = ftc_teams._fetch
        self.calls = []

    def tearDown(self):
        ftc_teams._fetch = self._orig_fetch

    def _stub(self, fetch):
        def wrapped(path, timeout=None):
            self.calls.append(path)
            return fetch(path)
        ftc_teams._fetch = wrapped

    def test_lookup_normalizes_a_real_team(self):
        self._stub(lambda path: dict(_SAMPLE))

        team = ftc_teams.lookup(16405)

        self.assertEqual(team["number"], 16405)
        self.assertEqual(team["name"], "Federal Bot Institute")
        self.assertEqual(team["location"], "Plano, TX, USA")
        self.assertEqual(team["rookie_year"], 2019)
        self.assertIsNone(team["website"])

    def test_lookup_returns_none_for_a_nonexistent_team(self):
        def fetch(path):
            raise _http_error(404)
        self._stub(fetch)

        self.assertIsNone(ftc_teams.lookup(999999999))

    def test_lookup_raises_when_registry_unreachable(self):
        def fetch(path):
            raise urllib.error.URLError("boom")
        self._stub(fetch)

        with self.assertRaises(ftc_teams.FtcApiError):
            ftc_teams.lookup(16405)

    def test_lookup_caches_and_does_not_refetch(self):
        self._stub(lambda path: dict(_SAMPLE))

        ftc_teams.lookup(16405)
        ftc_teams.lookup(16405)

        self.assertEqual(len(self.calls), 1)

    def test_absent_result_is_cached(self):
        def fetch(path):
            raise _http_error(404)
        self._stub(fetch)

        ftc_teams.lookup(999999999)
        ftc_teams.lookup(999999999)

        self.assertEqual(len(self.calls), 1)

    def test_search_returns_normalized_matches(self):
        self._stub(lambda path: [dict(_SAMPLE), {"number": 17897, "name": "Loose Screws"}])

        results = ftc_teams.search("federal")

        self.assertEqual([t["number"] for t in results], [16405, 17897])
        self.assertEqual(results[1]["name"], "Loose Screws")

    def test_search_skips_the_network_for_blank_text(self):
        self._stub(lambda path: [])

        self.assertEqual(ftc_teams.search("   "), [])
        self.assertEqual(self.calls, [])

    def test_search_returns_empty_on_error_via_describe_only(self):
        def fetch(path):
            raise urllib.error.URLError("down")
        self._stub(fetch)

        with self.assertRaises(ftc_teams.FtcApiError):
            ftc_teams.search("federal")

    def test_describe_classifies_each_state(self):
        self._stub(lambda path: dict(_SAMPLE))
        self.assertEqual(ftc_teams.describe(16405)["state"], "found")

        ftc_teams._cache.clear()
        self._stub(lambda path: (_ for _ in ()).throw(_http_error(404)))
        self.assertEqual(ftc_teams.describe(999999999)["state"], "absent")

        ftc_teams._cache.clear()
        self._stub(lambda path: (_ for _ in ()).throw(urllib.error.URLError("x")))
        self.assertEqual(ftc_teams.describe(16405)["state"], "error")


if __name__ == "__main__":
    unittest.main()
