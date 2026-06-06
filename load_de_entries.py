"""
Load DE_DATA (DR/DU) entry files into the entries table.

DE_DATA uses RA2/SE2 record format:
  DR{DATE}.DAT  - Race-level info  (RA2 records, 890+CRLF = 892 bytes/record)
  DU{DATE}.DAT  - Horse entry info (SE2 records, 157+CRLF = 159 bytes/record)

Key difference from ES_DATA (LR/LU / RAA/SEA):
  - bytes  3-10 = created_date (file preparation date)
  - bytes 11-18 = race_date    (actual race day)  ← reversed from RAA/SEA format
  - distance at bytes 697-700  (vs 616-619 in RAA)

Usage:
    python load_de_entries.py              # loads C:\\TFJV\\DE_DATA\\YYYY\\ for current year
    python load_de_entries.py 2026         # loads specified year
    python load_de_entries.py --all        # loads all years found under DE_DATA
"""

from __future__ import annotations

import sys
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

ROOT    = Path(__file__).parent
DB_PATH = ROOT / "data" / "keiba.db"
DE_ROOT = Path(r"C:\TFJV\DE_DATA")

sys.path.insert(0, str(ROOT))
from src.db.schema import init_db

# ── レコード定義 ──────────────────────────────────────────────────────────────
RA2_RECORD_LEN = 892
RA2_DATA_LEN   = 890
SE2_RECORD_LEN = 159
SE2_DATA_LEN   = 157

SJIS       = "shift_jis"
FULL_SPACE = "　"   # 全角スペース (0x8140)


def _ascii(raw: bytes, start: int, length: int) -> str:
    return raw[start : start + length].decode("ascii", errors="replace").strip()


def _sjis(raw: bytes, start: int, length: int) -> str:
    try:
        return raw[start : start + length].decode(SJIS, errors="replace").replace(FULL_SPACE, " ").strip()
    except Exception:
        return ""


def _int_field(raw: bytes, start: int, length: int) -> Optional[int]:
    s = _ascii(raw, start, length)
    try:
        v = int(s)
        return v if v > 0 else None
    except ValueError:
        return None


# ── データクラス ──────────────────────────────────────────────────────────────
@dataclass
class RA2Race:
    race_date    : str
    venue_code   : str
    meeting_num  : str
    day_num      : str
    race_num     : str
    race_name    : str
    grade_code   : str
    distance     : Optional[int]

    @property
    def race_key(self) -> str:
        return f"{self.race_date}{self.venue_code}{self.meeting_num}{self.day_num}{self.race_num}"


@dataclass
class SE2Horse:
    race_date    : str
    venue_code   : str
    meeting_num  : str
    day_num      : str
    race_num     : str
    gate_num     : str
    horse_num    : str
    blood_reg_num: str
    horse_name   : str
    horse_age    : Optional[int]
    sex_code     : str
    jockey_name  : str
    jockey_code  : str
    trainer_name : str

    @property
    def race_key(self) -> str:
        return f"{self.race_date}{self.venue_code}{self.meeting_num}{self.day_num}{self.race_num}"


# ── パーサー ──────────────────────────────────────────────────────────────────
def parse_ra2_record(raw: bytes) -> Optional[RA2Race]:
    if len(raw) < RA2_DATA_LEN:
        return None
    if raw[0:3] != b"RA2":
        return None

    grade_byte = chr(raw[614]) if len(raw) > 614 else " "
    grade_code = grade_byte if grade_byte.strip() else " "

    # distance at bytes 697-700 (confirmed from field analysis)
    distance = _int_field(raw, 697, 4)

    return RA2Race(
        race_date   = _ascii(raw, 11,  8),   # bytes 11-18 = actual race date
        venue_code  = _ascii(raw, 19,  2),
        meeting_num = _ascii(raw, 21,  2),
        day_num     = _ascii(raw, 23,  2),
        race_num    = _ascii(raw, 25,  2),
        race_name   = _sjis( raw, 32, 180),  # same position as RAA
        grade_code  = grade_code,
        distance    = distance,
    )


def parse_se2_record(raw: bytes) -> Optional[SE2Horse]:
    if len(raw) < SE2_DATA_LEN:
        return None
    if raw[0:3] != b"SE2":
        return None

    sex_byte = chr(raw[78]) if len(raw) > 78 and 0x31 <= raw[78] <= 0x33 else ""
    age_raw  = _ascii(raw, 82, 2)
    try:
        horse_age = int(age_raw) if age_raw.isdigit() else None
    except ValueError:
        horse_age = None

    return SE2Horse(
        race_date     = _ascii(raw, 11,  8),   # bytes 11-18 = actual race date
        venue_code    = _ascii(raw, 19,  2),
        meeting_num   = _ascii(raw, 21,  2),
        day_num       = _ascii(raw, 23,  2),
        race_num      = _ascii(raw, 25,  2),
        gate_num      = chr(raw[27]) if 0x30 <= raw[27] <= 0x38 else "",
        horse_num     = _ascii(raw, 28,  2),
        blood_reg_num = _ascii(raw, 30, 10),
        horse_name    = _sjis( raw, 40, 36),
        horse_age     = horse_age,
        sex_code      = sex_byte,
        jockey_name   = _sjis( raw, 90,  8),
        jockey_code   = _ascii(raw, 98,  6),
        trainer_name  = _sjis( raw, 122, 16),
    )


def parse_dr_file(path: Path) -> list[RA2Race]:
    data = path.read_bytes()
    n = len(data) // RA2_RECORD_LEN
    return [r for i in range(n)
            if (r := parse_ra2_record(data[i * RA2_RECORD_LEN : i * RA2_RECORD_LEN + RA2_DATA_LEN]))]


def parse_du_file(path: Path) -> list[SE2Horse]:
    data = path.read_bytes()
    n = len(data) // SE2_RECORD_LEN
    return [r for i in range(n)
            if (r := parse_se2_record(data[i * SE2_RECORD_LEN : i * SE2_RECORD_LEN + SE2_DATA_LEN]))]


# ── ローダー ──────────────────────────────────────────────────────────────────
def load_year(conn: sqlite3.Connection, year_dir: Path) -> tuple[int, int]:
    """Load all DR/DU files from year_dir into entries. Returns (races_loaded, horses_loaded)."""
    race_map: dict[str, RA2Race] = {}
    for dr_file in sorted(year_dir.glob("DR*.DAT")):
        for race in parse_dr_file(dr_file):
            race_map[race.race_key] = race

    if not race_map:
        print(f"  No RA2 race records found in {year_dir}")
        return 0, 0

    horse_entries: list[SE2Horse] = []
    for du_file in sorted(year_dir.glob("DU*.DAT")):
        horse_entries.extend(parse_du_file(du_file))

    if not horse_entries:
        print(f"  No SE2 horse records found in {year_dir}")
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
            race.race_name      if race else None,
            race.grade_code     if race else None,
            race.distance       if race else None,
            None,                                    # condition_text (not in RA2)
            h.horse_num,
            h.gate_num,
            h.blood_reg_num,
            h.horse_name,
            h.horse_age,
            h.sex_code,
            h.jockey_name,
            h.jockey_code,
            h.trainer_name,
            None,                                    # body_weight (not in SE2)
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
        years = [d.name for d in sorted(DE_ROOT.iterdir()) if d.is_dir() and d.name.isdigit()]
    else:
        for arg in sys.argv[1:]:
            if arg.isdigit():
                years.append(arg)
        if not years:
            years = [str(date.today().year)]

    conn = init_db(DB_PATH)

    total_races = total_horses = 0
    for year in years:
        year_dir = DE_ROOT / year
        if not year_dir.exists():
            print(f"Directory not found: {year_dir}")
            continue

        r, h = load_year(conn, year_dir)
        print(f"{year}: {r} races, {h} horse entries loaded")
        total_races += r
        total_horses += h

    print(f"\nTotal: {total_races} races, {total_horses} horse entries")

    # Show summary
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
