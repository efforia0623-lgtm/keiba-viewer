"""
UM_DATA SK*.DAT parser -- 馬マスタ (horse basic registration data)

File: C:/TFJV/UM_DATA/{YEAR}/SK{N}{YEAR}{PART}.DAT
Record: 208 bytes fixed-length (206 data + CRLF)

Note: SK files contain horse REGISTRATION data (biological info).
      Horse NAMES are in horse_results from SE data (not in SK files).

Confirmed field layout:
  0-  1  "SK"           record type
  2       data subtype ("1")
  3- 10  update_date   YYYYMMDD (file update date)
 11- 20  blood_reg_num 10 ASCII digits (e.g. "2025100002")
 21- 28  birth_date    YYYYMMDD
 29       sex_raw       "1"=牡, "2"=牝, "3"=騸 (1 byte)
 30- 31  unknown_30    (2 bytes)
 31- 32  coat_raw      毛色コード (2 bytes, 01=鹿毛,02=黒鹿,03=青鹿,04=青,05=芦,06=栗,...)
 33- 44  unknown_33    (12 bytes, likely includes production area code)
 45       pad byte
 46- 65  prod_area     産地 (20 bytes Shift-JIS, 10 full-width chars)
 66-205  pedigree_raw  父/母 blood regs + other stats (raw numeric)
206-207  CRLF
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RECORD_LEN = 208
DATA_LEN   = 206
SJIS = "shift_jis"

SEX_MAP  = {"1": "牡", "2": "牝", "3": "騸"}
COAT_MAP = {
    "01": "鹿毛", "02": "黒鹿毛", "03": "青鹿毛", "04": "青毛",
    "05": "芦毛", "06": "栗毛",  "07": "栃栗毛", "08": "白毛",
    "09": "佐目毛", "10": "淡栗毛",
}


def _ascii(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode("ascii", errors="replace").strip()


def _sjis(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode(SJIS, errors="replace").replace("　", " ").strip()


@dataclass
class HorseMaster:
    blood_reg_num : str
    birth_date    : Optional[str]
    sex_raw       : str
    coat_raw      : str
    prod_area     : str
    update_date   : str

    @property
    def sex_name(self) -> str:
        return SEX_MAP.get(self.sex_raw, self.sex_raw)

    @property
    def coat_name(self) -> str:
        return COAT_MAP.get(self.coat_raw, self.coat_raw)

    @property
    def birth_year(self) -> Optional[int]:
        if self.birth_date and len(self.birth_date) == 8:
            return int(self.birth_date[:4])
        return None


def parse_record(raw: bytes) -> Optional[HorseMaster]:
    if len(raw) < DATA_LEN:
        return None
    if raw[:2] != b"SK":
        return None
    blood = _ascii(raw, 11, 10)
    if not blood.isdigit():
        return None
    birth_raw = _ascii(raw, 21, 8)
    birth = birth_raw if birth_raw.isdigit() and birth_raw != "00000000" else None
    return HorseMaster(
        blood_reg_num = blood,
        birth_date    = birth,
        sex_raw       = _ascii(raw, 29, 1),
        coat_raw      = _ascii(raw, 31, 2),
        prod_area     = _sjis(raw, 46, 20),
        update_date   = _ascii(raw, 3, 8),
    )


def parse_file(dat_path: Path) -> list[HorseMaster]:
    data = dat_path.read_bytes()
    n = len(data) // RECORD_LEN
    return [r for i in range(n)
            if (r := parse_record(data[i * RECORD_LEN:i * RECORD_LEN + DATA_LEN]))]


def parse_year(year: int, root: Path = Path(r"C:\TFJV\UM_DATA")) -> list[HorseMaster]:
    year_dir = root / str(year)
    if not year_dir.exists():
        return []
    results = []
    for f in sorted(year_dir.glob("SK*.DAT")):
        results.extend(parse_file(f))
    return results


if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    horses = parse_year(2020)
    print(f"Parsed {len(horses)} horse records (2020)")
    for h in horses[:5]:
        print(f"  血統{h.blood_reg_num} 生{h.birth_date} {h.sex_name} {h.coat_name} 産地:{h.prod_area}")
