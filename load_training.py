"""Load CK_DATA (HC02/HC12) training records into keiba.db."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.parser.ck_parser import parse_file
from src.db.schema import get_conn, DB_PATH

CK_ROOT = Path(r"C:\TFJV\CK_DATA")

INSERT_SQL = """
INSERT OR REPLACE INTO training
    (training_date, training_time, blood_reg_num, venue_code,
     time_4f, time_2f, time_1f_first, time_1f_last, extra_raw, source_file)
VALUES (?,?,?,?,?,?,?,?,?,?)
"""


def create_table(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS training (
        training_date   TEXT NOT NULL,
        training_time   TEXT NOT NULL,
        blood_reg_num   TEXT NOT NULL,
        venue_code      TEXT,
        time_4f         REAL,
        time_2f         REAL,
        time_1f_first   REAL,
        time_1f_last    REAL,
        extra_raw       TEXT,
        source_file     TEXT,
        PRIMARY KEY (training_date, training_time, blood_reg_num)
    );
    CREATE INDEX IF NOT EXISTS idx_tr_date  ON training(training_date);
    CREATE INDEX IF NOT EXISTS idx_tr_blood ON training(blood_reg_num);
    CREATE INDEX IF NOT EXISTS idx_tr_venue ON training(venue_code);
    CREATE INDEX IF NOT EXISTS idx_tr_4f    ON training(time_4f);
    CREATE INDEX IF NOT EXISTS idx_tr_1f    ON training(time_1f_last);
    """)
    conn.commit()


def main():
    conn = get_conn(DB_PATH)
    create_table(conn)

    dat_files = sorted(CK_ROOT.rglob("HC0[12]*.DAT"))
    print(f"Found {len(dat_files)} HC02/HC12 DAT files")

    total_records = 0
    total_inserted = 0
    t0 = time.time()

    for i, fpath in enumerate(dat_files, 1):
        records = parse_file(fpath)
        total_records += len(records)

        rows = [
            (r.training_date, r.training_time, r.blood_reg_num, r.venue_code,
             r.time_4f, r.time_2f, r.time_1f_first, r.time_1f_last,
             r.extra_raw, r.source_file)
            for r in records
        ]
        if rows:
            conn.executemany(INSERT_SQL, rows)
            total_inserted += len(rows)

        if i % 500 == 0 or i == len(dat_files):
            conn.commit()
            elapsed = time.time() - t0
            print(f"  [{i}/{len(dat_files)}] files | {total_records:,} parsed | "
                  f"{total_inserted:,} inserted | {elapsed:.0f}s")

    conn.commit()
    elapsed = time.time() - t0

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM training")
    db_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(training_date), MAX(training_date) FROM training")
    date_range = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT blood_reg_num) FROM training")
    unique_horses = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT venue_code) FROM training")
    unique_venues = cur.fetchone()[0]

    print(f"\n=== Done in {elapsed:.0f}s ===")
    print(f"Files processed : {len(dat_files):,}")
    print(f"Records parsed  : {total_records:,}")
    print(f"DB rows         : {db_count:,}")
    print(f"Date range      : {date_range[0]} ~ {date_range[1]}")
    print(f"Unique horses   : {unique_horses:,}")
    print(f"Unique venues   : {unique_venues}")

    print("\nSample rows (2026):")
    cur.execute("""
        SELECT training_date, training_time, blood_reg_num, venue_code,
               time_4f, time_2f, time_1f_last
        FROM training WHERE training_date LIKE '2026%'
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"  {row[0]} {row[1]} horse={row[2]} venue={row[3]} "
              f"4F={row[4]}s 2F={row[5]}s 1F={row[6]}s")

    conn.close()


if __name__ == "__main__":
    main()
