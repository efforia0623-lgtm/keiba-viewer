# -*- coding: utf-8 -*-
"""
Add track_type / dist_class / distance columns to horse_results.
Step 1: ALTER TABLE (idempotent)
Step 2: UPDATE all years 2011-2026 from SU*.DAT files
"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.db.schema import DB_PATH, get_conn
from src.parser.su_parser import parse_file

DATA_ROOT = Path(r"C:\TFJV\SE_DATA")
YEARS     = range(2011, 2027)

# ── Step 1: add columns (ignore if already exists) ──────────────────────────
conn = get_conn(DB_PATH)
for col, typ in [("track_type", "TEXT"), ("dist_class", "TEXT"), ("distance", "INTEGER")]:
    try:
        conn.execute(f"ALTER TABLE horse_results ADD COLUMN {col} {typ}")
        print(f"  Added column: {col}")
    except Exception:
        print(f"  Column already exists: {col}")
conn.commit()

# ── Step 2: UPDATE per-race (one UPDATE covers all horses in a race) ─────────
# Since track_type/dist_class/distance are race-level (same for all horses),
# extract from the first horse record per race and update the whole race at once.
UPDATE_SQL = """
UPDATE horse_results
SET track_type=?, dist_class=?, distance=?
WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
  AND track_type IS NULL
"""

t0 = time.time()
grand_total_races = 0

for year in YEARS:
    year_dir = DATA_ROOT / str(year)
    files = sorted(year_dir.glob("SU*.DAT"))
    if not files:
        continue

    year_races = 0
    # collect one representative record per race (first horse = most reliable)
    from collections import OrderedDict
    for f in files:
        records = parse_file(f)
        seen = OrderedDict()
        for r in records:
            key = (r.race_date, r.venue_code, r.meeting_num, r.day_num, r.race_num)
            if key not in seen:
                seen[key] = r

        batch = []
        for (rd, vc, mn, dn, rn), r in seen.items():
            if r.track_type:  # only if we decoded a valid track type
                batch.append((r.track_type, r.dist_class, r.distance,
                               rd, vc, mn, dn, rn))

        if batch:
            conn.executemany(UPDATE_SQL, batch)
            conn.commit()
            year_races += len(batch)

    grand_total_races += year_races
    elapsed = time.time() - t0
    print(f"  {year}: {year_races:>5} races updated  [{elapsed:.1f}s]")

elapsed = time.time() - t0
print(f"\nDone: {grand_total_races:,} races updated in {elapsed:.1f}s")

# ── Step 3: verify ────────────────────────────────────────────────────────────
print("\n=== track_type distribution ===")
for row in conn.execute("""
    SELECT track_type, COUNT(1) as n
    FROM horse_results GROUP BY track_type ORDER BY n DESC
"""):
    print(f"  {row[0]!r:10s}: {row[1]:>8,}")

print("\n=== distance distribution (top 20) ===")
for row in conn.execute("""
    SELECT track_type, distance, COUNT(1) as n
    FROM horse_results
    WHERE distance IS NOT NULL
    GROUP BY track_type, distance
    ORDER BY n DESC
    LIMIT 20
"""):
    print(f"  {row[0]:8s} {row[1]:5}m : {row[2]:>8,}")

print("\n=== NULL check ===")
null_cnt = conn.execute("SELECT COUNT(1) FROM horse_results WHERE track_type IS NULL").fetchone()[0]
total    = conn.execute("SELECT COUNT(1) FROM horse_results").fetchone()[0]
print(f"  track_type NULL: {null_cnt:,} / {total:,}")

conn.close()
print("\n=== Done ===")
