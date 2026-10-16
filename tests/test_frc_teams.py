import os
import unittest
from unittest.mock import patch

from robotics import frc_teams


_SAMPLE = {
    "teamNumber": 254,
    "nameFull": "The Cheesy Poofs",
    "city": "San Jose",
    "stateProv": "California",
    "country": "USA",
    "rookieYear": 1999,
    "website": "https://www.team254.com",
}


class FrcTeamsTests(unittest.TestCase):
    def setUp(self):
        frc_teams._cache.clear()
        self.fetch = patch.object(frc_teams, "_fetch")
        self.mock_fetch = self.fetch.start()

    def tearDown(self):
        self.fetch.stop()

    def test_lookup_normalizes_the_official_response(self):
        self.mock_fetch.return_value = {"teams": [_SAMPLE]}

        team = frc_teams.lookup(254)

        self.assertEqual(team["number"], 254)
        self.assertEqual(team["name"], "The Cheesy Poofs")
        self.assertEqual(team["location"], "San Jose, California, USA")
        self.assertEqual(team["rookie_year"], 1999)
        self.assertEqual(team["website"], "https://www.team254.com")

    def test_unsafe_team_website_is_not_exposed(self):
        unsafe = {**_SAMPLE, "website": "javascript:alert(1)"}
        self.mock_fetch.return_value = {"teams": [unsafe]}
        self.assertIsNone(frc_teams.lookup(254)["website"])

    def test_lookup_tries_the_previous_season(self):
        self.mock_fetch.side_effect = [{"teams": []}, {"teams": [_SAMPLE]}]

        team = frc_teams.lookup(254)

        self.assertEqual(team["number"], 254)
        self.assertEqual(self.mock_fetch.call_count, 2)

    def test_lookup_caches_a_team(self):
        self.mock_fetch.return_value = {"teams": [_SAMPLE]}
        frc_teams.lookup(254)
        frc_teams.lookup(254)
        self.assertEqual(self.mock_fetch.call_count, 1)

    def test_name_search_does_not_scan_the_whole_registry(self):
        self.assertEqual(frc_teams.search("Cheesy Poofs"), [])
        self.mock_fetch.assert_not_called()

    def test_missing_credentials_fail_without_leaking_values(self):
        self.fetch.stop()
        with patch.dict(os.environ, {"FRC_API_USERNAME": "", "FRC_API_TOKEN": ""}):
            with self.assertRaises(frc_teams.FrcApiError):
                frc_teams._credentials()
        self.fetch = patch.object(frc_teams, "_fetch")
        self.mock_fetch = self.fetch.start()


if __name__ == "__main__":
    unittest.main()
