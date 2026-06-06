"""Load parsed SU records into SQLite."""

import sqlite3
from pathlib import Path

from src.parser.su_parser import HorseResult, parse_file
from src.db.schema import init_db, DB_PATH

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
    track_type, dist_class, distance,
    tail_raw, source_file
) VALUES (
    ?,?,?,?,?,?,  ?,?,  ?,?,?,?,  ?,?,?,?,  ?,?,?,  ?,?,?,?,  ?,?,?,?,  ?,?,?,  ?,?,?,  ?,?
)
"""


def _to_row(r: HorseResult, source: str) -> tuple:
    return (
        r.race_date, r.venue_code, r.meeting_num, r.day_num, r.race_num, r.horse_num,
        r.gate_num, r.blood_reg_num,
        r.horse_name, r.horse_age, r.sex_code, r.coat_code,
        r.jockey_name, r.jockey_code, r.trainer_name, r.owner_name,
        r.silks_desc, r.horse_weight, r.weight_change,
        r.finish_pos, r.race_time, r.finish_margin, r.popularity,
        r.corner1, r.corner2, r.corner3, r.corner4,
        r.agari_3f, r.winner_blood_reg, r.winner_name,
        r.track_type, r.dist_class, r.distance,
        r.tail_raw, source,
    )


def load_file(dat_path: Path, conn: sqlite3.Connection) -> int:
    records = parse_file(dat_path)
    rows = [_to_row(r, dat_path.name) for r in records]
    conn.executemany(INSERT_SQL, rows)
    conn.commit()
    return len(rows)


def load_year(year: int,
              data_root: Path = Path(r"C:\TFJV\SE_DATA"),
              db_path: Path = DB_PATH,
              rebuild: bool = False) -> None:
    year_dir = data_root / str(year)
    files = sorted(year_dir.glob("SU*.DAT"))
    if not files:
        print(f"No SU*.DAT files in {year_dir}")
        return

    if rebuild:
        db_path.unlink(missing_ok=True)
        print(f"Rebuilt: {db_path}")

    conn = init_db(db_path)

    if rebuild:
        # Drop and recreate tables
        conn.executescript("""
            DROP TABLE IF EXISTS horse_results;
            DROP VIEW IF EXISTS v_race_entries;
            DROP VIEW IF EXISTS v_race_summary;
        """)
        from src.db.schema import SCHEMA_SQL
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    total = 0
    for f in files:
        n = load_file(f, conn)
        total += n
        print(f"  {f.name}: {n:>5} records  (cumulative: {total})")

    print(f"\nDone: {total} records from {len(files)} files ({year})")
    conn.close()


if __name__ == "__main__":
    import sys
    year    = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    rebuild = "--rebuild" in sys.argv
    load_year(year, rebuild=rebuild)
