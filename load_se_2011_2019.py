"""
2011-2019年の SU*.DAT を keiba.db へ追加ロード（既存データは保持）。
"""
import sys, sqlite3, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.parser.su_parser import parse_file
from src.db.schema import DB_PATH, get_conn

DATA_ROOT = Path(r"C:\TFJV\SE_DATA")
YEARS     = list(range(2011, 2020))

INSERT_SQL = """
INSERT OR REPLACE INTO horse_results (
    race_date, venue_code, meeting_num, day_num, race_num, horse_num,
    gate_num, blood_reg_num,
    horse_name, horse_age, sex_code, coat_code,
    jockey_name, jockey_code, trainer_name, owner_name,
    silks_desc, horse_weight, weight_change,
    finish_pos, race_time, finish_margin, popularity,
    corner1, corner2, corner3, corner4,
    agari_3f, winner_blood_reg, winner_name,
    tail_raw, source_file
) VALUES (?,?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?)
"""

def to_row(r, src):
    return (
        r.race_date, r.venue_code, r.meeting_num, r.day_num, r.race_num, r.horse_num,
        r.gate_num, r.blood_reg_num,
        r.horse_name, r.horse_age, r.sex_code, r.coat_code,
        r.jockey_name, r.jockey_code, r.trainer_name, r.owner_name,
        r.silks_desc, r.horse_weight, r.weight_change,
        r.finish_pos, r.race_time, r.finish_margin, r.popularity,
        r.corner1, r.corner2, r.corner3, r.corner4,
        r.agari_3f, r.winner_blood_reg, r.winner_name,
        r.tail_raw, src,
    )

# ── ファイル一覧 ──────────────────────────────────────────────────────────────
all_files = []
for year in YEARS:
    all_files += sorted((DATA_ROOT / str(year)).glob("SU*.DAT"))

total_files = len(all_files)
print(f"対象: {YEARS[0]}-{YEARS[-1]}年  計 {total_files} ファイル")
print(f"DB  : {DB_PATH}\n")

# ── DB接続（既存を保持、スキーマだけ確認） ────────────────────────────────────
conn = get_conn(DB_PATH)
before = conn.execute("SELECT COUNT(1) FROM horse_results").fetchone()[0]
print(f"ロード前 horse_results: {before:,}件\n")

# ── ロード ─────────────────────────────────────────────────────────────────
grand_total = 0
files_done  = 0
t_start     = time.time()

for year in YEARS:
    year_dir = DATA_ROOT / str(year)
    files    = sorted(year_dir.glob("SU*.DAT"))
    if not files:
        continue

    year_total = 0
    t_year     = time.time()
    print(f"── {year}年 ({len(files)} ファイル) ──────────────────────")

    for f in files:
        records = parse_file(f)
        rows    = [to_row(r, f.name) for r in records]
        conn.executemany(INSERT_SQL, rows)
        conn.commit()

        year_total  += len(rows)
        grand_total += len(rows)
        files_done  += 1

        elapsed = time.time() - t_start
        rate    = grand_total / elapsed if elapsed > 0 else 0
        remain  = (total_files - files_done) / (files_done / elapsed) if files_done > 0 else 0

        print(f"  {f.name}: {len(rows):>5}件  "
              f"[{files_done:>3}/{total_files}]  "
              f"累計{grand_total:>7,}件  "
              f"{rate:>6,.0f}件/s  残り{remain:>4.0f}s")

    print(f"  → {year}年小計: {year_total:,}件  ({time.time()-t_year:.1f}s)\n")

# ── 完了サマリー ──────────────────────────────────────────────────────────────
elapsed = time.time() - t_start
after   = conn.execute("SELECT COUNT(1) FROM horse_results").fetchone()[0]

print("="*60)
print(f"完了: 追加 {grand_total:,}件  ({elapsed:.1f}s  {grand_total/elapsed:,.0f}件/s)")
print(f"horse_results 総件数: {after:,}件  (追加前: {before:,}件)\n")

print("=== 年別レコード数 ===")
for row in conn.execute("""
    SELECT SUBSTR(race_date,1,4) yr, COUNT(1) n,
           COUNT(DISTINCT race_date||venue_code||meeting_num||day_num||race_num) races
    FROM horse_results GROUP BY yr ORDER BY yr
"""):
    print(f"  {row[0]}年: {row[1]:>7,}件  {row[2]:>4}レース")

conn.close()
print("\nDone.")
