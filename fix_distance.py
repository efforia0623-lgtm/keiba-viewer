# -*- coding: utf-8 -*-
"""
Refine the `distance` column using per-(venue, track_type, dist_class) avg time.
Maps each group to the nearest standard JRA distance.
"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path

DB_PATH = Path(r"C:\Users\effor\keiba-ai\data\keiba.db")

# Standard JRA distances (meters)
TURF_DISTS   = [1000, 1200, 1400, 1500, 1600, 1800, 2000, 2200, 2400, 2500, 3000, 3200, 3600, 4250]
DIRT_DISTS   = [1000, 1150, 1200, 1300, 1400, 1600, 1700, 1800, 2000, 2100, 2200, 2400, 2500, 2600]
JUMP_DISTS   = [2000, 2350, 2500, 2600, 2750, 3000, 3170, 3200, 3900, 4250]

SPEED_BY_TYPE = {'芝': 17.0, 'ダート': 16.0, '障害': 13.5}

def nearest_dist(estimated_m: float, candidates: list[int]) -> int:
    return min(candidates, key=lambda d: abs(d - estimated_m))

def time_str_to_sec(t: str) -> float | None:
    if not t or ':' not in t or '.' not in t:
        return None
    try:
        m, rest = t.split(':')
        s, f = rest.split('.')
        return int(m)*60 + int(s) + int(f)/10
    except Exception:
        return None

conn = sqlite3.connect(DB_PATH)

# Compute avg winner time per (venue_code, track_type, dist_class)
rows = conn.execute("""
    SELECT venue_code, track_type, dist_class,
           COUNT(1) n,
           AVG(CASE
               WHEN race_time != '' AND race_time LIKE '%:%'
               THEN CAST(substr(race_time,1,1) AS REAL)*60
                  + CAST(substr(race_time,3,2) AS REAL)
                  + CAST(substr(race_time,6,1) AS REAL)/10
           END) avg_sec
    FROM horse_results
    WHERE finish_pos = 1
      AND track_type IS NOT NULL
      AND dist_class IS NOT NULL
      AND dist_class != ''
    GROUP BY venue_code, track_type, dist_class
    HAVING n >= 3
    ORDER BY venue_code, track_type, dist_class
""").fetchall()

updates = []
print(f"{'venue':6s} {'type':8s} cls  n_races  avg_t  →  dist")
for vc, tt, dc, n, avg_sec in rows:
    if avg_sec is None:
        continue
    sp = SPEED_BY_TYPE.get(tt, 16.0)
    est = avg_sec * sp
    if tt == '芝':
        d = nearest_dist(est, TURF_DISTS)
    elif tt == 'ダート':
        d = nearest_dist(est, DIRT_DISTS)
    else:
        d = nearest_dist(est, JUMP_DISTS)
    updates.append((d, vc, tt, dc))
    print(f"  v{vc}  {tt:8s}  {dc}  {n:5d}  {avg_sec:5.1f}s → {d}m  (est {est:.0f}m)")

print(f"\nUpdating {len(updates)} (venue, track_type, dist_class) groups...")
conn.executemany("""
    UPDATE horse_results
    SET distance = ?
    WHERE venue_code=? AND track_type=? AND dist_class=?
""", updates)
conn.commit()

# Quick verification
print("\n=== Distance distribution after fix ===")
for row in conn.execute("""
    SELECT track_type, distance, COUNT(1) n
    FROM horse_results WHERE distance IS NOT NULL
    GROUP BY track_type, distance ORDER BY track_type, distance
"""):
    print(f"  {row[0]:8s} {row[1]:5d}m : {row[2]:>8,}")

conn.close()
print("\nDone.")
