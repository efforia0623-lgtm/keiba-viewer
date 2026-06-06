"""
Load UM / HY / KT master data into keiba.db.
Shows per-step progress.
"""
import sys, sqlite3, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.db.schema import DB_PATH, get_conn, SCHEMA_SQL
from src.parser.kisi_parser import parse_file as parse_kisi, KISI_PATH
from src.parser.um_parser   import parse_year  as parse_um_year
from src.parser.hy_parser   import parse_year  as parse_hy_year

YEARS = list(range(2020, 2027))

# ── Open / initialise DB ───────────────────────────────────────────────────
conn = get_conn(DB_PATH)
conn.executescript(SCHEMA_SQL)   # creates new tables, no-op for existing ones
conn.commit()

t0 = time.time()

# ══════════════════════════════════════════════════════════════════════════
# 1. 騎手 (Jockeys) from TFJ_KISI.DAT
# ══════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("1. 騎手マスタ (TFJ_KISI.DAT)")
print("=" * 60)
t1 = time.time()
jockeys = parse_kisi(KISI_PATH)
print(f"  Parsed {len(jockeys):,} jockeys  ({time.time()-t1:.1f}s)")

conn.executemany("""
INSERT OR REPLACE INTO jockeys
  (jockey_code, jockey_name, name_kana, birth_date, license_date, retire_date, is_active)
VALUES (?,?,?,?,?,?,?)
""", [(j.jockey_code, j.jockey_name, j.name_kana,
       j.birth_date, j.license_date, j.retire_date, int(j.is_active))
      for j in jockeys])
conn.commit()

active   = sum(1 for j in jockeys if j.is_active)
retired  = len(jockeys) - active
print(f"  Loaded: {len(jockeys):,} total  (現役{active} / 引退{retired})")


# ══════════════════════════════════════════════════════════════════════════
# 2. 馬マスタ (Horses) from UM_DATA SK files
# ══════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print(f"2. 馬マスタ (UM_DATA 年別)")
print("=" * 60)

um_root = Path(r"C:\TFJV\UM_DATA")
um_years = sorted(y for y in um_root.iterdir() if y.is_dir() and y.name.isdigit())
print(f"  対象: {um_years[0].name}〜{um_years[-1].name}年  ({len(um_years)}年分)\n")

um_total = 0
t2 = time.time()
for yd in um_years:
    yr = int(yd.name)
    horses = parse_um_year(yr)
    if not horses:
        continue
    conn.executemany("""
    INSERT OR REPLACE INTO horses
      (blood_reg_num, birth_date, sex_raw, coat_raw, prod_area, update_date)
    VALUES (?,?,?,?,?,?)
    """, [(h.blood_reg_num, h.birth_date, h.sex_raw, h.coat_raw,
           h.prod_area, h.update_date) for h in horses])
    conn.commit()
    um_total += len(horses)
    print(f"  {yr}: {len(horses):>6,} 頭  [累計 {um_total:>7,}]")

print(f"  → 馬マスタ合計: {um_total:,} 頭  ({time.time()-t2:.1f}s)")


# ══════════════════════════════════════════════════════════════════════════
# 3. 払戻 (Payouts) from HY_DATA HY1*.DAT
# ══════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print(f"3. 払戻データ (HY_DATA {YEARS[0]}-{YEARS[-1]}年)")
print("=" * 60)

hy_total = 0
t3 = time.time()
for year in YEARS:
    payouts = parse_hy_year(year)
    if not payouts:
        print(f"  {year}: (no data)")
        continue
    conn.executemany("""
    INSERT OR REPLACE INTO payouts
      (race_date, venue_code, meeting_num, day_num, race_num,
       starters, finishers, race_class, payout_raw, source_file)
    VALUES (?,?,?,?,?, ?,?,?,?,?)
    """, [(p.race_date, p.venue_code, p.meeting_num, p.day_num, p.race_num,
           p.starters, p.finishers, p.race_class, p.payout_raw, p.source_file)
          for p in payouts])
    conn.commit()
    hy_total += len(payouts)
    print(f"  {year}: {len(payouts):>5,} レース  [累計 {hy_total:>6,}]")

print(f"  → 払戻合計: {hy_total:,} レース  ({time.time()-t3:.1f}s)")


# ══════════════════════════════════════════════════════════════════════════
# 4. Summary
# ══════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print(f"完了  総経過: {time.time()-t0:.1f}s")
print("=" * 60)
print()
print("=== テーブル件数 ===")
for tbl, label in [
    ("horse_results", "馬毎レース成績"),
    ("jockeys",       "騎手マスタ"),
    ("horses",        "馬登録マスタ"),
    ("payouts",       "払戻データ"),
]:
    n = conn.execute(f"SELECT COUNT(1) FROM {tbl}").fetchone()[0]
    print(f"  {tbl:<20} {n:>10,}  ({label})")

print()
print("=== 検証サンプル ===")
# Jockey: show active jockeys
print("現役騎手 (上位5):")
for row in conn.execute("""
    SELECT j.jockey_code, j.jockey_name, j.birth_date,
           COUNT(r.jockey_code) as rides,
           SUM(r.finish_pos=1) as wins
    FROM jockeys j
    LEFT JOIN horse_results r ON r.jockey_code = j.jockey_code
    WHERE j.is_active=1
    GROUP BY j.jockey_code
    ORDER BY rides DESC LIMIT 5
"""):
    print(f"  {row[0]} {row[1]} 生{row[2]}  {row[4]}/{row[3]}勝")

# Horse: link with race results
print("\n馬マスタ×成績 一致率:")
row = conn.execute("""
    SELECT COUNT(DISTINCT r.blood_reg_num) as in_results,
           COUNT(DISTINCT h.blood_reg_num) as in_horses,
           (SELECT COUNT(DISTINCT r2.blood_reg_num) FROM horse_results r2
            JOIN horses h2 ON r2.blood_reg_num=h2.blood_reg_num) as matched
    FROM horse_results r, horses h
""").fetchone()
print(f"  成績に馬: {row[0]:,}頭  馬マスタ: {row[1]:,}頭  両方: {row[2]:,}頭")

# Payout: races with payouts
print("\n払戻×成績 一致率:")
row = conn.execute("""
    SELECT COUNT(1) FROM payouts p
    JOIN horse_results r
      ON p.race_date=r.race_date AND p.venue_code=r.venue_code
     AND p.meeting_num=r.meeting_num AND p.day_num=r.day_num
     AND p.race_num=r.race_num
""").fetchone()
print(f"  払戻と成績が結合できるレコード数: {row[0]:,}")

conn.close()
print("\nDone.")
