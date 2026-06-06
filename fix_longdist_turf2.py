# -*- coding: utf-8 -*-
"""
Fix long-distance flat turf race misclassification - SAFE version.

Strategy: only fix cases with NO ambiguity:
1. ダート 2200m → 芝 2200m  (JRA に 2200m ダートコースなし)
2. ダート 2500m → 芝 2500m  (JRA に 2500m ダートコースなし)
3. ダート 2600m → 芝 2600m  (JRA に 2600m ダートコースなし)
4. 障害 d=1 at v08(京都) → 芝 3200m  (天皇賞春)
5. 障害 d=0 at v08(京都) → 芝 3000m  (菊花賞3000m等)
6. 障害 d=0 at v09(阪神) → 芝 2500m  (宝塚記念等)

ROLLBACK 前回の誤修正:
- v07/v08/v09 で dist_class='0' かつ距離=2000m → ダート 2000m に戻す
"""
import sys, sqlite3, time
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r'C:\Users\effor\keiba-ai\data\keiba.db'
conn = sqlite3.connect(DB_PATH)
t0 = time.time()

# ── STEP 0: 前回の誤修正をロールバック ─────────────────────────────────────
print("=== STEP 0: 前回誤修正のロールバック ===")

# v07/v08/v09 の dist_class=0 かつ distance=2000 は 2000m ダートなので戻す
n = conn.execute("""
    UPDATE horse_results SET track_type='ダート'
    WHERE track_type='芝' AND dist_class='0' AND distance=2000
      AND venue_code IN ('07','08','09')
""").rowcount
print(f"  Reverted {n:,} records: v07/08/09 芝(cls=0,2000m) → ダート 2000m")

# v06(中山)のダートとして残るべきレースを確認・修正
# 中山 ダート cls=3(2400m): 正しい ダート 2400m レースを芝に変えてしまったかもしれない
# 中山 ダート cls=3 avg=155.0s のうち、時間<152sは有馬記念(芝2500m)、>155sは ダート 2400m
# ただし当面は芝2500mのままでOK(有馬記念候補は正しく芝化)

# 大きな 2000m ダート の全般的な間違いをロールバック
# 本来 2000m ダートが存在する v07/v08/v09 で relabel された全てを戻す
n2 = conn.execute("""
    UPDATE horse_results SET track_type='ダート'
    WHERE track_type='芝' AND distance=2000 AND dist_class='0'
      AND venue_code IN ('07','08','09')
""").rowcount  # dist_class='0' が ダート 2000m を意味するv07/08/09
# これは上のqueryと重複するがsafe

conn.commit()
print(f"  (additional check: {n2} records)")

# ── STEP 1: JRA に存在しない ダートコース長を 芝 に修正 ──────────────────────
print()
print("=== STEP 1: ダート非存在距離を 芝 に修正 ===")

# JRA ダートコース最大距離: 2400m (中山のみ), 2100m, 2000m...
# 2200m, 2500m, 2600m ダートは JRA に存在しない
for dist, label in [(2200, 'ダート 2200m → 芝 2200m'),
                    (2500, 'ダート 2500m → 芝 2500m'),
                    (2600, 'ダート 2600m → 芝 2600m')]:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝'
        WHERE track_type='ダート' AND distance=?
    """, (dist,)).rowcount
    print(f"  {label}: {n:,} records")

conn.commit()

# ── STEP 2: ダート 2400m → 速度でふるい分け (15.2m/s cutoff) ───────────────
print()
print("=== STEP 2: ダート 2400m → 速度で芝/ダート判定 ===")

# 2400m 芝 (Japan Derby等) winner: < 155s → speed > 15.5m/s
# 2400m ダート (中山等)  winner: > 155s → speed < 15.5m/s
# 安全のため threshold 155sを使い、ダートが存在しない会場は全て芝へ
# ダート 2400m が存在する会場: v06 (中山のみ、ただし中山でも芝2400mレースあり)

# 2400m ダートが存在しない会場: v04(新潟),v05(東京),v07(中京),v08(京都),v09(阪神)
# → これらの "ダート 2400m" は全て平地芝 2400m
for vc, vname in [('04','新潟'), ('05','東京'), ('07','中京'), ('08','京都'), ('09','阪神')]:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝'
        WHERE track_type='ダート' AND distance=2400 AND venue_code=?
    """, (vc,)).rowcount
    print(f"  v{vc}({vname}) ダート 2400m → 芝 2400m: {n:,} records")

# v06(中山): ダート 2400m が存在するが、有馬記念2500m芝も混在
# cls=3 の中で、速度で判定: winner time < 155s → 芝、>= 155s → ダート維持
# ここでは保守的に残す(v06の 2400m ダートはそのまま)
print(f"  v06(中山) ダート 2400m: 保留 (混在のため個別確認推奨)")

conn.commit()

# ── STEP 3: 障害 長距離平地芝レースを修正 ───────────────────────────────────
print()
print("=== STEP 3: 障害 → 平地芝 修正 ===")

# v08(京都) 障害 dist_class=1 → 天皇賞春(3200m), その他長距離芝
# 勝ち時間で判定: < 205s なら平地芝 (3200m at 16m/s = 200s)
# 3020m 京都障害: winner typically > 220s → > 205s

# 天皇賞春 (v08, dist_class=1, winner < 205s)
# dist_class=1 の障害レースを全て確認
tenno_races = conn.execute("""
    SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num
    FROM horse_results
    WHERE track_type='障害' AND dist_class='1' AND venue_code='08'
      AND finish_pos=1
      AND CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 < 205
      AND race_time != '' AND race_time LIKE '%:%'
""").fetchall()

n_tenno = 0
for rd, vc, mn, dn, rn in tenno_races:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝', distance=3200
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
          AND track_type='障害'
    """, (rd, vc, mn, dn, rn)).rowcount
    n_tenno += n

print(f"  天皇賞春 (v08 障害 cls=1, winner<205s) → 芝 3200m: {n_tenno:,} records ({len(tenno_races)} races)")

# 菊花賞 (v08, dist_class=0, 3000m, winner < 200s)
kikka_races = conn.execute("""
    SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num
    FROM horse_results
    WHERE track_type='障害' AND dist_class='0' AND venue_code='08'
      AND substr(race_date,5,4) BETWEEN '0901' AND '1130'
      AND finish_pos=1
      AND CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 < 200
      AND race_time != '' AND race_time LIKE '%:%'
""").fetchall()
n_kikka = 0
for rd, vc, mn, dn, rn in kikka_races:
    n = conn.execute("""
        UPDATE horse_results SET track_type='芝', distance=3000
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
          AND track_type='障害'
    """, (rd, vc, mn, dn, rn)).rowcount
    n_kikka += n
print(f"  菊花賞等 (v08 障害 cls=0, 9-11月, winner<200s) → 芝 3000m: {n_kikka:,} records ({len(kikka_races)} races)")

conn.commit()

# ── STEP 4: 最終確認 ────────────────────────────────────────────────────────
print()
print("=== 最終 track_type × distance 分布 ===")
for row in conn.execute("""
    SELECT track_type, distance, COUNT(1) n
    FROM horse_results WHERE distance IS NOT NULL
    GROUP BY track_type, distance ORDER BY track_type, distance
"""):
    tt, d, n = row
    if d is None: continue
    print(f"  {str(tt):8s} {str(d):5}m : {n:>8,}")

print()
print("=== 有名長距離レース 最終確認 ===")
for horse in ['キタサンブラック','コントレイル','ロジャーバローズ','フィエールマン']:
    for row in conn.execute("""
        SELECT horse_name, race_date, venue_code, race_time,
            CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 t,
            track_type, distance
        FROM horse_results WHERE horse_name LIKE ? AND finish_pos=1
          AND CAST(substr(race_time,1,1) AS REAL)*60+CAST(substr(race_time,3,2) AS REAL)+CAST(substr(race_time,6,1) AS REAL)/10 > 135
        ORDER BY race_date
    """, (f'%{horse}%',)):
        hn,rd,vc,rt,t,tt,d = row
        print(f"  {hn} {rd} v{vc} {rt}({t:.1f}s) track={tt!r} dist={d}m")

null_cnt = conn.execute("SELECT COUNT(1) FROM horse_results WHERE track_type IS NULL").fetchone()[0]
total = conn.execute("SELECT COUNT(1) FROM horse_results").fetchone()[0]
print(f"\n  NULL track_type: {null_cnt:,}/{total:,}")
print(f"  Elapsed: {time.time()-t0:.1f}s")
conn.close()
print("\nDone.")
