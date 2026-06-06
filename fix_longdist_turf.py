# -*- coding: utf-8 -*-
"""
Fix mislabeled long-distance flat turf races.

Root cause: JRA-VAN pos537 encoding:
  '1' = standard turf (1000-2200m)
  '2' = "long" category: includes ダート AND flat turf 2400m+
  '3' = "very long" category: includes jump races AND flat turf 3000m+

Strategy: use per-race winner speed to determine surface type.
- Flat turf speed at 2400m+: typically 15.5-17.5 m/s
- Dirt speed at 2400m+:    typically 13.5-15.5 m/s
- Jump race speed at 2500m+: typically 12.5-14.0 m/s
"""
import sys, sqlite3, time
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r'C:\Users\effor\keiba-ai\data\keiba.db'
conn = sqlite3.connect(DB_PATH)

t0 = time.time()

# ── Step 1: Build per-race winner speed table ──────────────────────────────
# For races where distance >= 2000m and track_type in ('ダート','障害')
print("Building per-race winner speeds...")
conn.execute("DROP TABLE IF EXISTS _tmp_race_speed")
conn.execute("""
CREATE TEMP TABLE _tmp_race_speed AS
SELECT
    race_date, venue_code, meeting_num, day_num, race_num,
    MIN(CAST(substr(race_time,1,1) AS REAL)*60
        + CAST(substr(race_time,3,2) AS REAL)
        + CAST(substr(race_time,6,1) AS REAL)/10) AS winner_time,
    AVG(distance) AS dist,
    MIN(CAST(substr(race_time,1,1) AS REAL)*60
        + CAST(substr(race_time,3,2) AS REAL)
        + CAST(substr(race_time,6,1) AS REAL)/10)
        / AVG(distance) AS inv_speed
FROM horse_results
WHERE track_type IN ('ダート', '障害')
  AND distance >= 2000
  AND finish_pos = 1
  AND race_time != '' AND race_time LIKE '%:%'
GROUP BY race_date, venue_code, meeting_num, day_num, race_num
""")
conn.commit()
print(f"  Per-race speed table built.")

# ── Step 2: Identify races to relabel ─────────────────────────────────────
# Speed threshold: flat turf races run faster than dirt/jump
# 2400m flat turf winner: typically < 160s → speed > 0.0625 (1/16m/s)
# 2400m dirt winner:     typically > 155s → speed < 0.0645 (1/15.5m/s)
# Use inv_speed < 1/15.5 = 0.06452 as "clearly turf" threshold
# Also handle 3200m天皇賞春: winner ~195s at 3200m (if dist is wrong 2600m,
#   use time < 205s AND dist in (2500, 2600) AND venue='08' for Tenno Sho)

TURF_SPEED_THRESHOLD = 1.0 / 15.5   # inv_speed < this → flat turf

print()
print("=== Races to relabel (inv_speed < 1/15.5 m/s, OR Tenno Sho pattern) ===")

# Count before fix
for label, sql in [
    ("ダート 2400m records", "SELECT COUNT(1) FROM horse_results WHERE track_type='ダート' AND distance=2400"),
    ("ダート 2500m records", "SELECT COUNT(1) FROM horse_results WHERE track_type='ダート' AND distance=2500"),
    ("ダート 2200m records", "SELECT COUNT(1) FROM horse_results WHERE track_type='ダート' AND distance=2200"),
    ("障害 2600m d=1 at Kyoto", "SELECT COUNT(1) FROM horse_results WHERE track_type='障害' AND dist_class='1' AND venue_code='08'"),
]:
    n = conn.execute(sql).fetchone()[0]
    print(f"  Before: {label}: {n:,}")

# ── Step 3a: Fix flat turf races labeled as ダート ─────────────────────────
# Find races where winner ran at turf speed
print()
print("Fixing ダート long-distance flat turf races...")

# Get race keys for turf-speed ダート races
turf_races = conn.execute("""
    SELECT r.race_date, r.venue_code, r.meeting_num, r.day_num, r.race_num,
           s.winner_time, s.dist, s.inv_speed
    FROM _tmp_race_speed s
    JOIN (SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num
          FROM horse_results WHERE track_type='ダート') r
    ON s.race_date=r.race_date AND s.venue_code=r.venue_code
       AND s.meeting_num=r.meeting_num AND s.day_num=r.day_num
       AND s.race_num=r.race_num
    WHERE s.inv_speed < ?
    ORDER BY s.winner_time
""", (TURF_SPEED_THRESHOLD,)).fetchall()

print(f"  Found {len(turf_races)} ダート races to relabel as 芝")
print("  Sample (fastest turf-speed ダート races):")
for rd, vc, mn, dn, rn, wt, d, inv in turf_races[:10]:
    speed = 1/inv
    print(f"    {rd} v{vc} R{rn} winner={wt:.1f}s dist={d:.0f}m speed={speed:.1f}m/s")

# Apply fix for ダート → 芝
turf_keys = [(rd, vc, mn, dn, rn) for rd, vc, mn, dn, rn, *_ in turf_races]
updated_dirt = 0
for rd, vc, mn, dn, rn in turf_keys:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝'
        WHERE race_date=? AND venue_code=? AND meeting_num=?
          AND day_num=? AND race_num=? AND track_type='ダート'
    """, (rd, vc, mn, dn, rn)).rowcount
    updated_dirt += n

conn.commit()
print(f"  Updated {updated_dirt:,} ダート records → 芝")

# ── Step 3b: Fix 天皇賞春 (3200m平地) labeled as 障害 at Kyoto ──────────────
# v08 障害 dist_class='1': winner_time < 205s → flat turf 3200m
print()
print("Fixing 天皇賞春 and similar 3200m flat turf at Kyoto (v08)...")

# Also fix other venues with 障害 cls=0 that are actually flat turf
# v08 障害 cls=0: avg winner 186s → at 16m/s = 2976m → 3000m flat (菊花賞?)
# v09 障害 cls=0: avg winner 185s → likely Hanshin flat long races

tenno_fix_data = conn.execute("""
    SELECT s.race_date, s.venue_code, s.meeting_num, s.day_num, s.race_num,
           s.winner_time, s.dist, s.inv_speed
    FROM _tmp_race_speed s
    JOIN (SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num
          FROM horse_results WHERE track_type='障害') r
    ON s.race_date=r.race_date AND s.venue_code=r.venue_code
       AND s.meeting_num=r.meeting_num AND s.day_num=r.day_num
       AND s.race_num=r.race_num
    WHERE s.inv_speed < ?
    ORDER BY s.venue_code, s.winner_time
""", (TURF_SPEED_THRESHOLD,)).fetchall()

print(f"  Found {len(tenno_fix_data)} 障害 races to relabel as 芝")
print("  Sample:")
for rd, vc, mn, dn, rn, wt, d, inv in tenno_fix_data[:10]:
    speed = 1/inv
    print(f"    {rd} v{vc} R{rn} winner={wt:.1f}s dist={d:.0f}m speed={speed:.1f}m/s")

tenno_keys = [(rd, vc, mn, dn, rn) for rd, vc, mn, dn, rn, *_ in tenno_fix_data]
updated_jump = 0
for rd, vc, mn, dn, rn in tenno_keys:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝'
        WHERE race_date=? AND venue_code=? AND meeting_num=?
          AND day_num=? AND race_num=? AND track_type='障害'
    """, (rd, vc, mn, dn, rn)).rowcount
    updated_jump += n
conn.commit()
print(f"  Updated {updated_jump:,} 障害 records → 芝")

# ── Step 4: Fix distances for relabeled races ────────────────────────────
# After relabeling track_type, recalculate distance using turf speed (17m/s)
print()
print("Recalculating distances for relabeled records...")

JRA_TURF_DISTS = [1000, 1200, 1400, 1500, 1600, 1800, 2000,
                  2200, 2400, 2500, 3000, 3200, 3600, 4250]

def nearest_turf(est_m):
    return min(JRA_TURF_DISTS, key=lambda d: abs(d - est_m))

# Get winner times for relabeled races
relabeled_keys = set(turf_keys + tenno_keys)
dist_updates = []
for rd, vc, mn, dn, rn in relabeled_keys:
    row = conn.execute("""
        SELECT MIN(CAST(substr(race_time,1,1) AS REAL)*60
                   + CAST(substr(race_time,3,2) AS REAL)
                   + CAST(substr(race_time,6,1) AS REAL)/10)
        FROM horse_results
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
          AND finish_pos=1 AND race_time!='' AND race_time LIKE '%:%'
    """, (rd, vc, mn, dn, rn)).fetchone()
    if row and row[0]:
        est = row[0] * 17.0
        d = nearest_turf(est)
        dist_updates.append((d, rd, vc, mn, dn, rn))

conn.executemany("""
    UPDATE horse_results SET distance=?
    WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
""", dist_updates)
conn.commit()
print(f"  Updated distances for {len(dist_updates)} races")

# ── Step 5: Summary ────────────────────────────────────────────────────────
print()
print("=== Final distribution ===")
for row in conn.execute("""
    SELECT track_type, distance, COUNT(1) n
    FROM horse_results WHERE distance IS NOT NULL
    GROUP BY track_type, distance ORDER BY track_type, distance
"""):
    print(f"  {str(row[0]):8s} {str(row[1]):5d}m : {row[2]:>8,}")

# Verify famous horses
print()
print("=== 有名長距離馬の track_type 確認 ===")
for horse in ['キタサンブラック','コントレイル','ロジャーバローズ','イクイノックス','フィエールマン']:
    for row in conn.execute("""
        SELECT horse_name, race_date, venue_code, race_time,
            CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 t,
            track_type, distance
        FROM horse_results WHERE horse_name LIKE ? AND finish_pos=1
          AND CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 > 135
        ORDER BY race_date
    """, (f'%{horse}%',)):
        hn,rd,vc,rt,t,tt,d = row
        print(f"  {hn} {rd} v{vc} {rt}({t:.1f}s) → track={tt!r} dist={d}m")

elapsed = time.time() - t0
print(f"\nDone in {elapsed:.1f}s")
conn.close()
