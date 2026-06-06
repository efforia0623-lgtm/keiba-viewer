"""Load pedigree data into keiba.db with progress display."""
import sys, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.db.schema import DB_PATH, get_conn, SCHEMA_SQL
from src.parser.bs_parser import build_uid_name_map, parse_all_pedigrees

INSERT_SQL = """
INSERT OR REPLACE INTO pedigree (
    blood_reg_num,
    father_uid,  father_name,   mother_uid,  mother_name,
    pat_gf_uid,  pat_gf_name,   pat_gm_uid,  pat_gm_name,
    mat_gf_uid,  mat_gf_name,   mat_gm_uid,  mat_gm_name,
    ppgf_uid, ppgf_name,  ppgm_uid, ppgm_name,
    pmgf_uid, pmgf_name,  pmgm_uid, pmgm_name,
    mpgf_uid, mpgf_name,  mpgm_uid, mpgm_name,
    mmgf_uid, mmgf_name,  mmgm_uid, mmgm_name
) VALUES (
    ?,
    ?,?,  ?,?,
    ?,?,  ?,?,
    ?,?,  ?,?,
    ?,?,  ?,?,
    ?,?,  ?,?,
    ?,?,  ?,?,
    ?,?,  ?,?
)
"""

def to_row(p):
    return (
        p.blood_reg_num,
        p.father_uid,  p.father_name,   p.mother_uid,  p.mother_name,
        p.pat_gf_uid,  p.pat_gf_name,   p.pat_gm_uid,  p.pat_gm_name,
        p.mat_gf_uid,  p.mat_gf_name,   p.mat_gm_uid,  p.mat_gm_name,
        p.ppgf_uid, p.ppgf_name,   p.ppgm_uid, p.ppgm_name,
        p.pmgf_uid, p.pmgf_name,   p.pmgm_uid, p.pmgm_name,
        p.mpgf_uid, p.mpgf_name,   p.mpgm_uid, p.mpgm_name,
        p.mmgf_uid, p.mmgf_name,   p.mmgm_uid, p.mmgm_name,
    )

t0 = time.time()
conn = get_conn(DB_PATH)
conn.executescript(SCHEMA_SQL)
conn.commit()

# ── Step 1: KT2 UID→name map ─────────────────────────────────────────
print("Step 1/3  KT2ファイルからUID→馬名マップを構築中...")
uid_map = build_uid_name_map()
print(f"  → {len(uid_map):,} UIDs  ({time.time()-t0:.1f}s)")

# ── Step 2: SK pedigree parsing ──────────────────────────────────────
print("\nStep 2/3  SK血統ファイルを解析中...")
t1 = time.time()
pedigrees = parse_all_pedigrees(uid_map)
print(f"  → {len(pedigrees):,} 血統レコード  ({time.time()-t1:.1f}s)")

# ── Step 3: DB insert ─────────────────────────────────────────────────
print("\nStep 3/3  keiba.dbに格納中...")
t2 = time.time()
BATCH = 5000
for start in range(0, len(pedigrees), BATCH):
    batch = pedigrees[start:start+BATCH]
    conn.executemany(INSERT_SQL, [to_row(p) for p in batch])
    conn.commit()
    done = min(start+BATCH, len(pedigrees))
    pct  = done / len(pedigrees) * 100
    print(f"  {done:>7,}/{len(pedigrees):,}  ({pct:.1f}%)  {time.time()-t2:.1f}s", end='\r')

print(f"\n  → 完了  ({time.time()-t2:.1f}s)")

# ── Summary ──────────────────────────────────────────────────────────
total = time.time() - t0
print(f"\n{'='*55}")
print(f"総処理時間: {total:.1f}s")

print("\n=== pedigreeテーブル確認 ===")
cur = conn.execute("SELECT COUNT(1) FROM pedigree")
print(f"  総レコード: {cur.fetchone()[0]:,}")

cur = conn.execute("SELECT COUNT(1) FROM pedigree WHERE father_name != ''")
print(f"  父名あり  : {cur.fetchone()[0]:,}")

cur = conn.execute("SELECT COUNT(1) FROM pedigree WHERE mother_name != ''")
print(f"  母名あり  : {cur.fetchone()[0]:,}")

cur = conn.execute("SELECT COUNT(1) FROM pedigree WHERE mat_gf_name != ''")
print(f"  母父名あり: {cur.fetchone()[0]:,}")

# Match with horse_results
cur = conn.execute("""
    SELECT COUNT(1) FROM horse_results r
    JOIN pedigree p ON r.blood_reg_num = p.blood_reg_num
""")
print(f"\n  成績×血統 結合可能: {cur.fetchone()[0]:,} レコード")

print("\n=== 2020年レースの血統サンプル (top5 by 父名) ===")
for row in conn.execute("""
    SELECT r.horse_name, p.father_name, p.mother_name,
           p.pat_gf_name, p.mat_gf_name
    FROM horse_results r
    JOIN pedigree p ON r.blood_reg_num = p.blood_reg_num
    WHERE r.race_date LIKE '2026%'
      AND p.father_name != ''
    LIMIT 8
"""):
    print(f"  {row[0]:<14} 父:{row[1]:<14} 母:{row[2]:<14}"
          f" 父父:{row[3]:<12} 母父:{row[4]}")

print("\n=== 母父ランキング (2026年成績、上位10) ===")
for row in conn.execute("""
    SELECT p.mat_gf_name, COUNT(1) as n,
           SUM(CASE WHEN r.finish_pos=1 THEN 1 ELSE 0 END) as wins
    FROM horse_results r
    JOIN pedigree p ON r.blood_reg_num = p.blood_reg_num
    WHERE r.race_date LIKE '2026%' AND p.mat_gf_name != ''
    GROUP BY p.mat_gf_name
    ORDER BY n DESC LIMIT 10
"""):
    print(f"  {row[0]:<20} {row[1]:>5}頭 {row[2]:>4}勝")

conn.close()
print("\nDone.")
