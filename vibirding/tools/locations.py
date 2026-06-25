"""Place name -> coordinates, the small lookup range_check relies on.

eBird only accepts lat/lng, not place names. We keep a hand-maintained table of
the spots you actually visit, keyed by their STANDARD official name (the system
prompt already corrects notes to that standard name, so an exact match suffices).
Add a spot by adding one line below. A miss returns None, and range_check turns
that into a graceful "unknown place" fallback rather than an error.
"""

from __future__ import annotations

# Standard official place name -> (latitude, longitude). Coordinates are the
# rough center of the site; eBird's default 25 km radius covers the rest.
PLACE_COORDS: dict[str, tuple[float, float]] = {
    "葛西临海公园": (35.6418, 139.8606),  # Kasai Rinkai Park, Tokyo
    "三宅岛": (34.0833, 139.5167),  # Miyake-jima
    "高尾山": (35.6254, 139.2437),  # Mount Takao, Hachioji, Tokyo
    "东京港野鸟公园": (35.5839, 139.7603),  # Tokyo Port Wild Bird Park, Ota, Tokyo
    "明治神宫": (35.6764, 139.6993),  # Meiji Jingu, Shibuya, Tokyo
    "登户": (35.6311, 139.5660),  # Noborito Station, Tama Ward, Kawasaki
    "水元公园": (35.7849, 139.8701),  # Mizumoto Park, Katsushika, Tokyo
    "井之头恩赐公园": (35.6997, 139.5737),  # Inokashira Park, Musashino, Tokyo
}


def resolve_place(place: str | None) -> tuple[float, float] | None:
    """Return the spot's (lat, lng), or None if it isn't in the table.

    Exact match on the trimmed name only (minimal on purpose) — the prompt hands
    us the standardized name. None is a normal outcome, not an error.
    """
    if not place:
        return None
    return PLACE_COORDS.get(place.strip())
