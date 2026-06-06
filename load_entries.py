"""
Load ES_DATA entry files into the entries table.

Usage:
    python load_entries.py              # loads C:\\TFJV\\ES_DATA\\YYYY\\ for current year
    python load_entries.py 2026         # loads specified year
    python load_entries.py --all        # loads all years found under ES_DATA

Run this after updating TF-JV each morning.
"""

from __future__ import annotations

import sys
import sqlite3
from datetime import date
from pathlib import Path

ROOT     = Path(__file__).parent
DB_PATH  = ROOT / "data" / "keiba.db"
ES_ROOT  = Path(r"C:\TFJV\ES_DATA")

sys.path.insert(0, str(ROOT))
from src.parser.entry_parser import (
    parse_lr_file, parse_lu_file,
    RaceEntry, HorseEntry,
)
from src.db.schema import init_db


def load_year(conn: sqlite3.Connection, year_dir: Path) -> tuple[int, int]:
    """Load all LR/LU files from year_dir into entries. Returns (races_loaded, horses_loaded)."""
    # Build race info map: race_key → RaceEntry
    race_map: dict[str, RaceEntry] = {}
    for lr_file in sorted(year_dir.glob("LR*.DAT")):
        for race in parse_lr_file(lr_file):
            race_map[race.race_key] = race

    if not race_map:
        return 0, 0

    # Parse all horse entries
    horse_entries: list[HorseEntry] = []
    for lu_file in sorted(year_dir.glob("LU*.DAT")):
        horse_entries.extend(parse_lu_file(lu_file))

    if not horse_entries:
        return 0, 0

    rows = []
    for h in horse_entries:
        race = race_map.get(h.race_key)
        rows.append((
            h.race_date,
            h.venue_code,
            h.meeting_num,
            h.day_num,
            h.race_num,
            race.race_name       if race else None,
            race.grade_code      if race else None,
            race.distance        if race else None,
            race.condition_text  if race else None,
            h.horse_num,
            h.gate_num,
            h.blood_reg_num,
            h.horse_name,
            h.horse_age,
            h.sex_code,
            h.jockey_name,
            h.jockey_code,
            h.trainer_name,
            h.body_weight,
            str(year_dir),
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO entries (
            race_date, venue_code, meeting_num, day_num, race_num,
            race_name, grade_code, distance, condition_text,
            horse_num, gate_num, blood_reg_num, horse_name,
            horse_age, sex_code, jockey_name, jockey_code, trainer_name,
            body_weight, source_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    unique_races = len({(h.race_date, h.venue_code, h.meeting_num, h.day_num, h.race_num)
                        for h in horse_entries})
    return unique_races, len(rows)


def main():
    years: list[str] = []

    if "--all" in sys.argv:
        years = [d.name for d in sorted(ES_ROOT.iterdir()) if d.is_dir() and d.name.isdigit()]
    else:
        for arg in sys.argv[1:]:
            if arg.isdigit():
                years.append(arg)
        if not years:
            years = [str(date.today().year)]

    conn = init_db(DB_PATH)

    total_races = total_horses = 0
    for year in years:
        year_dir = ES_ROOT / year
        if not year_dir.exists():
            print(f"Directory not found: {year_dir}")
            continue

        r, h = load_year(conn, year_dir)
        print(f"{year}: {r} races, {h} horse entries loaded")
        total_races += r
        total_horses += h

    print(f"\nTotal: {total_races} races, {total_horses} horse entries")

    # Show summary of loaded data
    cur = conn.execute("""
        SELECT race_date, venue_code, COUNT(DISTINCT race_num) AS races, COUNT(*) AS horses
        FROM entries
        GROUP BY race_date, venue_code
        ORDER BY race_date DESC
        LIMIT 20
    """)
    print("\nRecent entries (top 20 date/venue combos):")
    for row in cur.fetchall():
        print(f"  {row[0]}  venue:{row[1]}  {row[2]}レース {row[3]}頭")


if __name__ == "__main__":
    main()
