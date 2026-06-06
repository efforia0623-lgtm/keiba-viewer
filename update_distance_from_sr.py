"""
Update horse_results.distance (and track_type) using exact values from SR*.DAT RA7 records.

SR*.DAT (SE_DATA/{year}/SR*.DAT):
  - Record type: RA7, 1270 bytes + CRLF per record
  - pos  0- 1: "RA"
  - pos  2   : '7' (data type)
  - pos  3-10: race_date  YYYYMMDD  (Monday after the race weekend, same as SU/DB)
  - pos 11-18: created_date
  - pos 19-20: venue_code
  - pos 21-22: meeting_num
  - pos 23-24: day_num     (same as DB day_num – the JOIN key)
  - pos 25-26: race_num
  - pos 697-700: distance in meters (4 ASCII digits, e.g. "2400", "1700")

Track-type correction:
  Where the SU-derived track_type is wrong (pos537 quirk), we correct it by
  looking up which distances are unambiguously dirt or hurdle at each venue.
  For ambiguous distances (e.g. Tokyo 1400m can be turf or dirt) we leave the
  existing track_type untouched.
"""

import glob
import sqlite3
from pathlib import Path
from collections import defaultdict

# ── Known unambiguous (venue, distance) → track_type mappings ─────────────────
# Only list entries where we are certain the distance is ONLY used on that surface.
# Turf/hurdle rows are omitted because turf is the default; only dirt-only
# and hurdle-only combos need explicit overrides.
VENUE_DIST_TRACK: dict[tuple[str, int], str] = {
    # Fukushima (03)
    ("03", 1150): "ダート",
    ("03", 1700): "ダート",
    # Niigata (04)
    ("04", 1200): None,   # ambiguous (inner=dirt 1200m exists at Niigata)
    ("04", 1800): None,   # ambiguous (outer turf + dirt inner 1800m)
    # Tokyo (05) – dirt: 1300, 1400, 1600 are ambiguous; 2100 turf only
    ("05", 2100): "芝",
    # Nakayama (06) – dirt: 1200, 1800; turf: 1200, 1800 → ambiguous; 2500 turf only
    ("06", 2500): "芝",
    # Chukyo (07) – dirt: 1200, 1400, 1800; ambiguous for most
    # Kyoto (08) – post-renovation: dirt 1400, 1800
    ("08", 1400): None,   # ambiguous (turf 1400 and dirt 1400 both exist)
    # Hanshin (09) – dirt: 1200, 1400, 1800
    ("09", 1200): None,   # ambiguous
    ("09", 1400): None,   # ambiguous
    # Kokura (10) – dirt: 1000, 1700
    ("10", 1000): "ダート",
    ("10", 1700): "ダート",
}

# ── Venue-distance pairs that are unambiguously hurdle ─────────────────────────
HURDLE_DIST = {
    # these distances only appear in hurdle races at their venue
    ("03", 2400): "障害",
    ("04", 2500): "障害",
    ("05", 2300): "障害",
    ("05", 2750): "障害",
    ("06", 2500): "障害",   # only used for 障害 at Nakayama
    ("07", 2600): "障害",
    ("08", 2750): "障害",
    ("08", 3170): "障害",
    ("09", 1920): "障害",
    ("10", 2200): "障害",
}


def parse_sr_files(se_data_root: str, year_from: int = 2011) -> dict:
    """
    Parse all SR*.DAT files from year_from onwards.

    Returns:
        dict  { (race_date, venue_code, day_num, race_num) : distance_int }
    """
    pattern = f"{se_data_root}/*/SR*.DAT"
    files = sorted(glob.glob(pattern))

    race_dist: dict[tuple, int] = {}
    processed = 0

    for fpath in files:
        year_str = Path(fpath).parent.name
        try:
            year = int(year_str)
        except ValueError:
            continue
        if year < year_from:
            continue

        with open(fpath, "rb") as f:
            data = f.read()

        records = data.split(b"\r\n")
        records = [r for r in records if len(r) == 1270]

        for rec in records:
            if rec[0:2] != b"RA" or rec[2:3] != b"7":
                continue

            race_date  = rec[ 3:11].decode("ascii", errors="replace")
            venue_code = rec[19:21].decode("ascii", errors="replace")
            day_num    = rec[23:25].decode("ascii", errors="replace")
            race_num   = rec[25:27].decode("ascii", errors="replace")

            dist_bytes = rec[697:701]
            try:
                dist = int(dist_bytes.decode("ascii"))
            except ValueError:
                continue

            if dist < 500 or dist > 4500:
                continue  # sanity check

            key = (race_date, venue_code, day_num, race_num)
            # Last file / last record wins (later files are more authoritative)
            race_dist[key] = dist
            processed += 1

    print(f"  Parsed {processed} RA7 records, {len(race_dist)} unique races")
    return race_dist


def infer_track_type(venue_code: str, distance: int) -> str | None:
    """
    Return the correct track_type if the (venue, distance) pair is unambiguous,
    otherwise None (leave existing value).
    """
    key = (venue_code, distance)
    if key in HURDLE_DIST:
        return HURDLE_DIST[key]
    if key in VENUE_DIST_TRACK:
        return VENUE_DIST_TRACK[key]
    return None


def apply_updates(db_path: str, race_dist: dict, dry_run: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cur = conn.cursor()

    dist_updated = 0
    track_updated = 0
    skipped = 0
    not_found = 0

    # Build lookup of current DB state in batches
    # We iterate over the SR dict and update matching rows
    BATCH = 10_000
    items = list(race_dist.items())

    for batch_start in range(0, len(items), BATCH):
        batch = items[batch_start:batch_start + BATCH]
        for key, new_dist in batch:
            race_date, venue_code, day_num, race_num = key

            # Fetch current values
            cur.execute("""
                SELECT DISTINCT distance, track_type
                FROM horse_results
                WHERE race_date=? AND venue_code=? AND day_num=? AND race_num=?
            """, (race_date, venue_code, day_num, race_num))
            rows = cur.fetchall()

            if not rows:
                not_found += 1
                continue

            cur_dist  = rows[0][0]  # distance (may be None)
            cur_track = rows[0][1]  # track_type

            # Determine new track_type
            new_track = infer_track_type(venue_code, new_dist)
            if new_track is None:
                new_track = cur_track  # keep existing

            dist_changed  = (cur_dist != new_dist)
            track_changed = (new_track is not None and cur_track != new_track)

            if not dist_changed and not track_changed:
                skipped += 1
                continue

            if not dry_run:
                if dist_changed and track_changed:
                    conn.execute("""
                        UPDATE horse_results
                        SET distance=?, track_type=?
                        WHERE race_date=? AND venue_code=? AND day_num=? AND race_num=?
                    """, (new_dist, new_track, race_date, venue_code, day_num, race_num))
                elif dist_changed:
                    conn.execute("""
                        UPDATE horse_results SET distance=?
                        WHERE race_date=? AND venue_code=? AND day_num=? AND race_num=?
                    """, (new_dist, race_date, venue_code, day_num, race_num))
                elif track_changed:
                    conn.execute("""
                        UPDATE horse_results SET track_type=?
                        WHERE race_date=? AND venue_code=? AND day_num=? AND race_num=?
                    """, (new_track, race_date, venue_code, day_num, race_num))

            if dist_changed:
                dist_updated += 1
            if track_changed:
                track_updated += 1

        if not dry_run:
            conn.commit()
        if batch_start % 100_000 == 0 and batch_start > 0:
            print(f"  Progress: {batch_start}/{len(items)} SR races processed …")

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n=== Results {'(DRY RUN)' if dry_run else ''} ===")
    print(f"  SR races total:          {len(items):>8,}")
    print(f"  Races not in DB:         {not_found:>8,}")
    print(f"  Distance updated:        {dist_updated:>8,}")
    print(f"  Track_type updated:      {track_updated:>8,}")
    print(f"  Already correct:         {skipped:>8,}")


def verify(db_path: str) -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("\n=== Verification: known races ===")

    # Find Derby 2024 day_num
    cur.execute("""SELECT DISTINCT day_num FROM horse_results
                   WHERE race_date='20240527' AND venue_code='05' AND race_num='11'""")
    derby_days = [r[0] for r in cur.fetchall()]
    print(f"  Derby 2024 day_nums in DB: {derby_days}")

    checks = [
        ("20240527", "05", "11", 2400, "日本ダービー2024(2400m)"),
        ("20260525", "05", "11", 2400, "日本ダービー2026(2400m)"),
        ("20260525", "05", "07", 2400, "東京2400m 2026 R07"),
        ("20260525", "05", "12", 2100, "東京2100m 2026 R12"),
    ]
    for race_date, venue, race_num, expected, label in checks:
        cur.execute("""
            SELECT DISTINCT day_num, distance, track_type FROM horse_results
            WHERE race_date=? AND venue_code=? AND race_num=?
        """, (race_date, venue, race_num))
        rows = cur.fetchall()
        if rows:
            for r in rows:
                ok = "OK" if r["distance"] == expected else "NG"
                print(f"  [{ok}] {label}: day={r['day_num']} dist={r['distance']} "
                      f"(expected {expected}), track={r['track_type']}")
        else:
            print(f"  [--] {label}: NOT IN DB")

    # Distance distribution after update
    print("\n=== Distance distribution (top 20) ===")
    cur.execute("""SELECT track_type, distance, COUNT(*) cnt
                   FROM horse_results WHERE distance IS NOT NULL
                   GROUP BY track_type, distance ORDER BY cnt DESC LIMIT 20""")
    for r in cur.fetchall():
        try:
            tt = r["track_type"] or "NULL"
            print(f"  {tt} {r['distance']}m : {r['cnt']:,}")
        except Exception:
            print(f"  {r}")
    conn.close()


if __name__ == "__main__":
    import sys
    import time

    SE_DATA = "C:/TFJV/SE_DATA"
    DB_PATH = "data/keiba.db"
    DRY_RUN = "--dry-run" in sys.argv

    print(f"{'DRY RUN' if DRY_RUN else 'LIVE UPDATE'}: Parsing SR*.DAT files …")
    t0 = time.time()
    race_dist = parse_sr_files(SE_DATA, year_from=2011)
    print(f"  Parse time: {time.time()-t0:.1f}s")

    print(f"\nApplying updates to {DB_PATH} …")
    t1 = time.time()
    apply_updates(DB_PATH, race_dist, dry_run=DRY_RUN)
    print(f"  Update time: {time.time()-t1:.1f}s")

    verify(DB_PATH)
    print(f"\nTotal time: {time.time()-t0:.1f}s")
