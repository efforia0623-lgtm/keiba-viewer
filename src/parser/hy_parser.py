"""
HY_DATA HY1*.DAT parser — 払戻データ (payout data)

File: C:\TFJV\HY_DATA\{YEAR}\HY1{YEAR}{ROUND}.DAT
Record: 517 bytes fixed-length (1 record = 1 race)

Confirmed field layout (header):
  0-  2  "H15"          record type
  3- 10  race_date      YYYYMMDD
 11- 18  created_date   YYYYMMDD
 19- 20  venue_code     開催場コード
 21- 22  meeting_num    開催回次
 23- 24  day_num        開催日次
 25- 26  race_num       レース番号
 27- 28  starters       出走頭数 (2 ASCII digits)
 29- 30  finishers      完走頭数 (2 ASCII digits)
 31- 37  flags          (7 bytes, often "7777777")
 38- 39  race_class     (2 bytes)
 40- 99  zeros          (60 bytes, zero-padded section)
100-516  payout_raw     417 bytes of payout data (raw, future analysis)

Payout payload (100-516) known structure overview:
  The 417-byte section contains amounts for all JRA bet types in sequence.
  Each bet type field includes: winning combination + payout yen + ticket count.
  Full decoding requires correlation with known payout data.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RECORD_LEN = 517
SJIS = "shift_jis"


def _ascii(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode("ascii", errors="replace").strip()


def _int2(raw: bytes, start: int) -> Optional[int]:
    s = raw[start:start + 2].decode("ascii", errors="replace").strip()
    return int(s) if s.isdigit() else None


@dataclass
class RacePayout:
    race_date   : str
    venue_code  : str
    meeting_num : str
    day_num     : str
    race_num    : str
    starters    : Optional[int]
    finishers   : Optional[int]
    race_class  : str
    source_file : str
    # Raw payout bytes for future decoding
    payout_raw  : str   # hex of bytes 100-516


def parse_record(raw: bytes, source: str = "") -> Optional[RacePayout]:
    if len(raw) < RECORD_LEN:
        return None
    if raw[:2] != b"H1":
        return None
    return RacePayout(
        race_date   = _ascii(raw,  3,  8),
        venue_code  = _ascii(raw, 19,  2),
        meeting_num = _ascii(raw, 21,  2),
        day_num     = _ascii(raw, 23,  2),
        race_num    = _ascii(raw, 25,  2),
        starters    = _int2(raw, 27),
        finishers   = _int2(raw, 29),
        race_class  = _ascii(raw, 38,  2),
        source_file = source,
        payout_raw  = raw[100:517].hex(),
    )


def parse_file(dat_path: Path) -> list[RacePayout]:
    data = dat_path.read_bytes()
    n = len(data) // RECORD_LEN
    src = dat_path.name
    return [r for i in range(n)
            if (r := parse_record(data[i * RECORD_LEN:(i + 1) * RECORD_LEN], src))]


def parse_year(year: int, root: Path = Path(r"C:\TFJV\HY_DATA")) -> list[RacePayout]:
    year_dir = root / str(year)
    if not year_dir.exists():
        return []
    results = []
    for f in sorted(year_dir.glob("HY1*.DAT")):
        results.extend(parse_file(f))
    return results


if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    payouts = parse_year(2026)
    print(f"Parsed {len(payouts)} payout records (2026)")
    for p in payouts[:5]:
        print(f"  {p.race_date} 会場{p.venue_code} R{p.race_num} {p.starters}頭出走")
