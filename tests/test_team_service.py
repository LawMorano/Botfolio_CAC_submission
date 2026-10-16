import unittest

from services import team_service


class _Connection:
    def __init__(self, team_count):
        self.team_count = team_count
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return self

    def fetchone(self):
        return {"n": self.team_count}


class TeamServiceTests(unittest.TestCase):
    def test_first_fifty_claims_are_founding_teams(self):
        connection = _Connection(49)

        self.assertEqual(team_service.is_founding_claim(connection), 1)
        self.assertEqual(connection.statement, "SELECT COUNT(*) AS n FROM teams")

    def test_claims_after_first_fifty_are_not_founding_teams(self):
        self.assertEqual(team_service.is_founding_claim(_Connection(50)), 0)

    def test_aggregate_design_stats_totals_all_visible_team_designs(self):
        designs = [
            {"download_count": 3, "like_count": 2, "visit_count": 10},
            {"download_count": 4, "like_count": 1, "visit_count": 8},
        ]

        self.assertEqual(
            team_service.aggregate_design_stats(designs),
            {"design_count": 2, "download_count": 7, "like_count": 3, "visit_count": 18},
        )

    def test_aggregate_design_stats_handles_empty_teams(self):
        self.assertEqual(
            team_service.aggregate_design_stats([]),
            {"design_count": 0, "download_count": 0, "like_count": 0, "visit_count": 0},
        )


if __name__ == "__main__":
    unittest.main()
