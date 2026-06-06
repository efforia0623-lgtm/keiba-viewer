"""
Build keiba.db from scratch: 2020-2026 SU*.DAT files.
Shows per-file and per-year progress with ETA.
"""
import sys, sqlite3, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.parser.su_parser import parse_file
from src.db.schema import DB_PATH, SCHEMA_SQL, get_conn

DATA_ROOT = Path(r"C:\TFJV\SE_DATA")
YEARS     = list(range(2020, 2027))

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
) VALUES (
    ?,?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?
)
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

# ── pre-flight: count total files ─────────────────────────────────────────
all_files = []
for year in YEARS:
    all_files += sorted((DATA_ROOT / str(year)).glob("SU*.DAT"))

total_files = len(all_files)
print(f"対象: {YEARS[0]}-{YEARS[-1]}年  計 {total_files} ファイル")
print(f"DB  : {DB_PATH}\n")

# ── rebuild DB ────────────────────────────────────────────────────────────
DB_PATH.unlink(missing_ok=True)
conn = get_conn(DB_PATH)
conn.executescript(SCHEMA_SQL)
conn.commit()

# ── load ──────────────────────────────────────────────────────────────────
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
        t_file = time.time()
        records = parse_file(f)
        rows    = [to_row(r, f.name) for r in records]
        conn.executemany(INSERT_SQL, rows)
        conn.commit()

        year_total  += len(rows)
        grand_total += len(rows)
        files_done  += 1

        # ETA calculation
        elapsed = time.time() - t_start
        rate    = grand_total / elapsed if elapsed > 0 else 0
        remain  = (total_files - files_done) / (files_done / elapsed) if files_done > 0 else 0

        print(f"  {f.name}: {len(rows):>5}件  "
              f"[{files_done:>3}/{total_files}]  "
              f"累計{grand_total:>7,}件  "
              f"速度{rate:>6,.0f}件/s  "
              f"残り{remain:>5.0f}s")

    yr_elapsed = time.time() - t_year
    print(f"  → {year}年小計: {year_total:,}件  ({yr_elapsed:.1f}s)\n")

# ── summary ───────────────────────────────────────────────────────────────
elapsed = time.time() - t_start
print("="*60)
print(f"完了: {grand_total:,}件  {elapsed:.1f}s ({grand_total/elapsed:,.0f}件/s)")

# ── quality check ─────────────────────────────────────────────────────────
print("\n=== 品質チェック ===")
checks = [
    ("総レコード数",       "SELECT COUNT(1) FROM horse_results"),
    ("ユニークレース",      "SELECT COUNT(DISTINCT race_date||venue_code||meeting_num||day_num||race_num) FROM horse_results"),
    ("ユニーク馬",         "SELECT COUNT(DISTINCT blood_reg_num) FROM horse_results"),
    ("着順なし(取消等)",    "SELECT COUNT(1) FROM horse_results WHERE finish_pos IS NULL"),
    ("上がり3Fあり",       "SELECT COUNT(1) FROM horse_results WHERE agari_3f IS NOT NULL"),
    ("1着+空白着差(正常)", "SELECT COUNT(1) FROM horse_results WHERE finish_pos=1 AND finish_margin=''"),
    ("2着以降+空白(異常)", "SELECT COUNT(1) FROM horse_results WHERE finish_pos>1 AND finish_margin=''"),
]
for label, sql in checks:
    val = conn.execute(sql).fetchone()[0]
    print(f"  {label:<22}: {val:>10,}")

print("\n=== 年別レコード数 ===")
for row in conn.execute("""
    SELECT SUBSTR(race_date,1,4) as yr, COUNT(1) as n,
           COUNT(DISTINCT race_date||venue_code||meeting_num||day_num||race_num) as races
    FROM horse_results GROUP BY yr ORDER BY yr
"""):
    print(f"  {row[0]}年: {row[1]:>7,}件  {row[2]:>4}レース")

print("\n=== 1番人気成績 (2020-2026) ===")
row = conn.execute("""
    SELECT COUNT(1), SUM(finish_pos=1), SUM(finish_pos<=3)
    FROM horse_results WHERE popularity=1 AND finish_pos IS NOT NULL
""").fetchone()
n, wins, places = row
print(f"  単勝率:{wins/n:.1%}  複勝率:{places/n:.1%}  (n={n:,})")

print("\n=== 上がり3F統計 ===")
row = conn.execute("""
    SELECT AVG(agari_3f), MIN(agari_3f), MAX(agari_3f)
    FROM horse_results WHERE agari_3f IS NOT NULL AND agari_3f BETWEEN 30 AND 50
""").fetchone()
print(f"  平均:{row[0]:.2f}s  最速:{row[1]:.1f}s  最遅:{row[2]:.1f}s")

conn.close()
print("\nBuild complete.")
