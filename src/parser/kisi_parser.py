"""
TFJ_KISI.DAT parser — 騎手マスタ (jockey master)

File: C:\TFJV\TFJ_KISI.DAT  (single flat file, ~6.5 MB)
Record: 4,173 bytes fixed-length

Confirmed field layout:
  0-  2  "KS1"/"KS2"   record type
  3- 10  as_of_date    YYYYMMDD
 11- 16  jockey_code   6 ASCII digits
 17- 24  license_date  YYYYMMDD (デビュー日)
 25- 32  retire_date   YYYYMMDD (引退日, "00000000" if still active)
 33- 40  birth_date    YYYYMMDD
 41- 72  name_sjis     32 bytes Shift-JIS (full-width, space-padded)
 73-102  name_kana     30 bytes half-width katakana (space-padded)
103-4172 stats_raw     career statistics (many numeric fields, raw)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RECORD_LEN = 4173
SJIS = "shift_jis"
KISI_PATH = Path(r"C:\TFJV\TFJ_KISI.DAT")


def _ascii(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode("ascii", errors="replace").strip()


def _sjis(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode(SJIS, errors="replace").replace("　", " ").strip()


def _date(raw: bytes, start: int) -> Optional[str]:
    s = _ascii(raw, start, 8)
    return s if s.isdigit() and s != "00000000" else None


@dataclass
class Jockey:
    jockey_code  : str
    jockey_name  : str
    name_kana    : str
    birth_date   : Optional[str]
    license_date : Optional[str]
    retire_date  : Optional[str]
    is_active    : bool


def parse_file(path: Path = KISI_PATH) -> list[Jockey]:
    data = path.read_bytes()
    n = len(data) // RECORD_LEN
    results = []
    for i in range(n):
        raw = data[i * RECORD_LEN:(i + 1) * RECORD_LEN]
        if raw[:2] != b"KS":
            continue
        code = _ascii(raw, 11, 6)
        if not code or not code.isdigit():
            continue
        retire_raw = _ascii(raw, 25, 8)
        retire_date = retire_raw if retire_raw.isdigit() and retire_raw != "00000000" else None
        results.append(Jockey(
            jockey_code  = code,
            jockey_name  = _sjis(raw, 41, 32),
            name_kana    = _ascii(raw, 73, 30).strip(),
            birth_date   = _date(raw, 33),
            license_date = _date(raw, 17),
            retire_date  = retire_date,
            is_active    = (retire_date is None),
        ))
    return results


if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    jockeys = parse_file()
    print(f"Parsed {len(jockeys)} jockeys")
    for j in jockeys[:5]:
        status = "現役" if j.is_active else f"引退{j.retire_date}"
        print(f"  {j.jockey_code} {j.jockey_name}  生{j.birth_date}  {status}")
    active = sum(1 for j in jockeys if j.is_active)
    print(f"  Active: {active}, Retired: {len(jockeys)-active}")
