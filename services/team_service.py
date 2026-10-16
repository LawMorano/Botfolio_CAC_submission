"""Database-neutral helpers for team membership and ownership workflows."""


FOUNDING_TEAM_LIMIT = 50


def is_founding_claim(conn):
    """Return 1 while the first 50 team claims are being created."""
    row = conn.execute("SELECT COUNT(*) AS n FROM teams").fetchone()
    return int(row["n"] < FOUNDING_TEAM_LIMIT)


def aggregate_design_stats(designs):
    """Summarize engagement across the visible designs on a team page."""
    designs = list(designs)
    return {
        "design_count": len(designs),
        "download_count": sum(int(design["download_count"] or 0) for design in designs),
        "like_count": sum(int(design["like_count"] or 0) for design in designs),
        "visit_count": sum(int(design["visit_count"] or 0) for design in designs),
    }
