"""Rebuild keiba.db from scratch with updated schema and parser."""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from src.db.schema import DB_PATH, SCHEMA_SQL, get_conn
from src.db.loader import load_file
from src.parser.su_parser import parse_file

DATA_ROOT = Path(r"C:\TFJV\SE_DATA")
YEARS = range(2026, 2027)   # extend later

# Remove old DB
DB_PATH.unlink(missing_ok=True)
print(f"Removed old DB, rebuilding: {DB_PATH}\n")

conn = get_conn(DB_PATH)
conn.executescript(SCHEMA_SQL)
conn.commit()

from src.db.loader import INSERT_SQL, _to_row as to_row_base

def to_row(r, src):
    return to_row_base(r, src)

grand_total = 0
t0 = time.time()

for year in YEARS:
    year_dir = DATA_ROOT / str(year)
    files = sorted(year_dir.glob("SU*.DAT"))
    if not files:
        print(f"  {year}: no files found")
        continue
    year_total = 0
    print(f"=== {year} ({len(files)} files) ===")
    for f in files:
        records = parse_file(f)
        rows = [to_row(r, f.name) for r in records]
        conn.executemany(INSERT_SQL, rows)  # noqa: includes track_type/distance
        conn.commit()
        year_total += len(rows)
        print(f"  {f.name}: {len(rows):>5} records  [total {year_total}]")
    grand_total += year_total
    print(f"  → {year} subtotal: {year_total}\n")

elapsed = time.time() - t0
print(f"{'='*50}")
print(f"Grand total: {grand_total:,} records in {elapsed:.1f}s")

# Quick quality check
print("\n=== Quality check ===")
for sql, label in [
    ("SELECT COUNT(1) FROM horse_results", "Total records"),
    ("SELECT COUNT(DISTINCT race_date||venue_code||race_num) FROM horse_results", "Unique races"),
    ("SELECT COUNT(DISTINCT blood_reg_num) FROM horse_results", "Unique horses"),
    ("SELECT COUNT(1) FROM horse_results WHERE finish_pos IS NULL", "Missing finish_pos"),
    ("SELECT COUNT(1) FROM horse_results WHERE race_time=''", "Missing race_time"),
    ("SELECT COUNT(1) FROM horse_results WHERE finish_pos=1", "Winners recorded"),
]:
    val = conn.execute(sql).fetchone()[0]
    print(f"  {label}: {val:,}")

print("\n=== Race 1 winner sample (2026-04-13 Fukushima) ===")
for row in conn.execute("""
    SELECT horse_num, horse_name, finish_pos, race_time, finish_margin,
           popularity, corner1, corner2, corner3, corner4,
           horse_weight, weight_change
    FROM horse_results
    WHERE race_date='20260413' AND venue_code='03' AND race_num='01'
    ORDER BY finish_pos NULLS LAST
    LIMIT 5
"""):
    print(f"  {row[2]}着 H{row[0]} {row[1]} {row[3]} 差:{row[4]!r} "
          f"人気{row[5]} C:{row[6]}-{row[7]}-{row[8]}-{row[9]} "
          f"{row[10]}kg({row[11]})")

conn.close()
print("\nDone.")
