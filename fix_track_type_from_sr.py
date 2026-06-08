"""
SR*.DAT (RA7レコード) の byte705 を正式なtrack_typeとして
horse_results を全件上書き更新するスクリプト。

RA7レコード フィールド:
  0- 1: 'RA'
  2:    '7'
  3-10: race_date (YYYYMMDD)
 19-20: venue_code
 21-22: meeting_num
 23-24: day_num
 25-26: race_num
697-700: distance (4-digit ASCII, e.g. '1800')
    705: track_type_code ('1'=芝, '2'=ダート, '3'=障害)
"""
import sys, io, sqlite3, glob
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SE_DATA = Path(r'C:\TFJV\SE_DATA')
DB_PATH = Path('data/keiba.db')
TRACK_TYPE_MAP = {'1': '芝', '2': 'ダート', '3': '障害'}

# ── Step 1: 全SR*.DATからrace_mapを構築 ────────────────────────────────────
print('=== SR*.DAT 全年読み込み ===')
race_map: dict[tuple, tuple] = {}  # (race_date, venue_code, meeting_num, day_num, race_num) → (track_type, distance)

year_dirs = sorted(SE_DATA.glob('2*'))
for year_dir in year_dirs:
    sr_files = sorted(year_dir.glob('SR*.DAT'))
    if not sr_files:
        continue
    year_count = 0
    for dat in sr_files:
        data = dat.read_bytes()
        lines = data.split(b'\r\n')
        for line in lines:
            if len(line) < 710:
                continue
            if line[:2] != b'RA':
                continue
            rd = line[3:11].decode('ascii', errors='replace').strip()
            vc = line[19:21].decode('ascii', errors='replace').strip()
            mn = line[21:23].decode('ascii', errors='replace').strip()
            dn = line[23:25].decode('ascii', errors='replace').strip()
            rn = line[25:27].decode('ascii', errors='replace').strip()
            dist_raw = line[697:701].decode('ascii', errors='replace')
            b705 = chr(line[705]) if 0x30 <= line[705] <= 0x39 else ''
            track_type = TRACK_TYPE_MAP.get(b705, '')
            if not track_type or not rd:
                continue
            try:
                distance = int(dist_raw) if dist_raw.strip().isdigit() and int(dist_raw) > 0 else None
            except ValueError:
                distance = None
            key = (rd, vc, mn, dn, rn)
            race_map[key] = (track_type, distance)
            year_count += 1
    print(f'  {year_dir.name}: {len(sr_files)} ファイル, {year_count} レース')

print(f'\n合計: {len(race_map):,} レース')
from collections import Counter
tt_dist = Counter(v[0] for v in race_map.values())
print(f'track_type分布: {dict(tt_dist)}')

# ── Step 2: horse_resultsを一括更新 ─────────────────────────────────────────
print()
print('=== horse_results 更新 ===')
conn = sqlite3.connect(DB_PATH)

# 全horse_resultsのrace_keyを取得（一意なレースのみ）
print('全レースキーを取得中...')
race_keys = conn.execute("""
    SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num
    FROM horse_results
""").fetchall()
print(f'horse_results 収録レース数: {len(race_keys):,}')

# SR*.DATと照合してtrack_type/distanceが違うレースを更新
update_tt_only = []
update_both = []
update_dist_only = []

current_map = {}
rows = conn.execute("""
    SELECT DISTINCT race_date, venue_code, meeting_num, day_num, race_num, track_type, distance
    FROM horse_results
""").fetchall()
for r in rows:
    current_map[(r[0], r[1], r[2], r[3], r[4])] = (r[5], r[6])

for key, (sr_tt, sr_dist) in race_map.items():
    if key not in current_map:
        continue
    db_tt, db_dist = current_map[key]
    tt_diff = (sr_tt != db_tt and sr_tt)
    dist_diff = (sr_dist is not None and sr_dist != db_dist)

    if tt_diff and dist_diff:
        update_both.append((sr_tt, sr_dist) + key)
    elif tt_diff:
        update_tt_only.append((sr_tt,) + key)
    elif dist_diff:
        update_dist_only.append((sr_dist,) + key)

print(f'track_type + distance 両方更新: {len(update_both):,}件')
print(f'track_type のみ更新:           {len(update_tt_only):,}件')
print(f'distance のみ更新:             {len(update_dist_only):,}件')

# 更新実行
if update_both:
    conn.executemany("""
        UPDATE horse_results SET track_type=?, distance=?
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
    """, update_both)
if update_tt_only:
    conn.executemany("""
        UPDATE horse_results SET track_type=?
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
    """, update_tt_only)
if update_dist_only:
    conn.executemany("""
        UPDATE horse_results SET distance=?
        WHERE race_date=? AND venue_code=? AND meeting_num=? AND day_num=? AND race_num=?
    """, update_dist_only)

conn.commit()

total_updated = len(update_both) + len(update_tt_only) + len(update_dist_only)
print(f'\n更新完了: 合計 {total_updated:,} レース')

# ── Step 3: 全体track_type分布確認 ──────────────────────────────────────────
print()
print('=== 更新後のtrack_type分布 ===')
rows = conn.execute("""
    SELECT track_type, COUNT(*) as cnt
    FROM horse_results
    GROUP BY track_type
    ORDER BY cnt DESC
""").fetchall()
for r in rows:
    print(f'  {r[0]!r:8}: {r[1]:>9,}件')

# ── Step 4: ルクソールカフェ確認 ────────────────────────────────────────────
print()
print('=== ルクソールカフェ(2022110083) 更新後 ===')
rows = conn.execute("""
    SELECT race_date, venue_code, track_type, dist_class, distance,
           race_time, agari_3f, finish_pos
    FROM horse_results
    WHERE blood_reg_num='2022110083'
    ORDER BY race_date
""").fetchall()
for r in rows:
    mark = '✓ ダート' if r[2] == 'ダート' else '× 芝'
    print(f'  {r[0]} v{r[1]} {r[2]:5} {r[4]:4}m cls:{r[3]} {r[5]} agari:{r[6]} {r[7]}着  {mark}')

conn.close()
print('\n完了')
