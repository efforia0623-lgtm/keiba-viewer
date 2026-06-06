"""
Entry (出馬表) parser for TARGET frontier JV ES_DATA files.

File naming convention (ES_DATA/YYYY/):
  LR{YEAR}{KAISAI:02d}{VENUE:02d}.DAT  - Race-level info (RAA records)
  LU{YEAR}{KAISAI:02d}{VENUE:02d}.DAT  - Horse entry info (SEA records)

Record sizes:
  LR (RAA): 1272 bytes = 1270 data + CRLF
  LU (SEA): 555 bytes  = 553 data  + CRLF

Verified field layout:

LR (RAA) record — race entry info:
   0-  2  "RAA"  record identifier
   3- 10  race_date        YYYYMMDD
  11- 18  created_date     YYYYMMDD
  19- 20  venue_code       開催場コード (NAR: 30=門別, 42=浦和, 43=船橋, 44=大井,
                                          45=川崎, 47=笠松, 48=名古屋, 50=園田,
                                          51=姫路, 54=高知, 55=佐賀)
  21- 22  meeting_num      開催回次
  23- 24  day_num          開催日次
  25- 26  race_num         レース番号
  32-211  race_name        レース名 (SJIS, 180 bytes, full-width space padded)
 212-535  condition_text   条件 ASCII e.g. "TOKUBETSU(THREE-YEAR-OLD OP)"
     614  grade_code       レースグレード ('A'=最高,'B','C','D','E',' '=一般)
 616-619  distance         距離 m (4-digit ASCII; '0000' if unknown)

LU (SEA) record — horse entry info:
   0-  2  "SEA"  record identifier
   3- 10  race_date        YYYYMMDD  (same as LR key)
  11- 18  created_date     YYYYMMDD
  19- 20  venue_code       開催場コード
  21- 22  meeting_num      開催回次
  23- 24  day_num          開催日次
  25- 26  race_num         レース番号
      27  gate_num         枠番 (1 ASCII digit)
  28- 29  horse_num        馬番 (2 ASCII digits)
  30- 39  blood_reg_num    血統登録番号 (10 ASCII digits)
  40- 75  horse_name       馬名 (SJIS, 36 bytes)
      78  sex_code         性別 '1'=牡, '2'=牝, '3'=騸
  82- 83  horse_age        馬齢 (2 ASCII digits, e.g. "07"=7歳)
  90- 97  jockey_name      騎手名 (SJIS, 8 bytes)
  98-103  jockey_code      騎手コード (6 ASCII digits)
 288-290  body_weight      馬体重 kg (3 ASCII digits; '000' if unknown)
 306-321  trainer_name     調教師名 (SJIS, 16 bytes)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LR_RECORD_LEN = 1272
LU_RECORD_LEN = 555
LR_DATA_LEN   = 1270
LU_DATA_LEN   = 553

SJIS       = "shift_jis"
FULL_SPACE = "　"   # 0x8140 full-width space

NAR_VENUE_NAMES = {
    "30": "門別",  "31": "北見",  "32": "岩見沢", "33": "帯広",
    "34": "旭川",  "35": "盛岡",  "36": "水沢",   "38": "上山",
    "42": "浦和",  "43": "船橋",  "44": "大井",   "45": "川崎",
    "46": "金沢",  "47": "笠松",  "48": "名古屋", "50": "園田",
    "51": "姫路",  "54": "高知",  "55": "佐賀",   "65": "帯広(ばんえい)",
    # JRA codes (01-10) for completeness
    "01": "札幌",  "02": "函館",  "03": "福島",   "04": "新潟",
    "05": "東京",  "06": "中山",  "07": "中京",   "08": "京都",
    "09": "阪神",  "10": "小倉",
}

SEX_MAP = {"1": "牡", "2": "牝", "3": "騸", "": "不明"}

GRADE_MAP = {
    "A": "GⅠ相当", "B": "GⅡ相当", "C": "GⅢ相当",
    "D": "重賞",   "E": "特別",    " ": "一般",
}


def _strip_sjis(raw: bytes) -> str:
    try:
        return raw.decode(SJIS, errors="replace").replace(FULL_SPACE, " ").strip()
    except Exception:
        return ""


def _ascii(raw: bytes, start: int, length: int) -> str:
    return raw[start:start + length].decode("ascii", errors="replace").strip()


def _sjis(raw: bytes, start: int, length: int) -> str:
    return _strip_sjis(raw[start:start + length])


def _int_field(raw: bytes, start: int, length: int) -> Optional[int]:
    s = _ascii(raw, start, length)
    try:
        v = int(s)
        return v if v > 0 else None
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RaceEntry:
    """Race-level information from LR (RAA) records."""
    race_date     : str
    venue_code    : str
    meeting_num   : str
    day_num       : str
    race_num      : str
    race_name     : str
    condition_text: str
    grade_code    : str   # 'A'-'E' or ' '
    distance      : Optional[int]   # meters, None if unknown

    @property
    def race_key(self) -> str:
        return f"{self.race_date}{self.venue_code}{self.meeting_num}{self.day_num}{self.race_num}"

    @property
    def venue_name(self) -> str:
        return NAR_VENUE_NAMES.get(self.venue_code, self.venue_code)

    @property
    def grade_label(self) -> str:
        return GRADE_MAP.get(self.grade_code, "")


@dataclass
class HorseEntry:
    """Horse-level information from LU (SEA) records."""
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
    sex_code     : str   # '1'=牡, '2'=牝, '3'=騸
    jockey_name  : str
    jockey_code  : str
    trainer_name : str
    body_weight  : Optional[int]   # kg

    @property
    def race_key(self) -> str:
        return f"{self.race_date}{self.venue_code}{self.meeting_num}{self.day_num}{self.race_num}"

    @property
    def sex_name(self) -> str:
        return SEX_MAP.get(self.sex_code, self.sex_code)


# ─────────────────────────────────────────────────────────────────────────────

def parse_lr_record(raw: bytes) -> Optional[RaceEntry]:
    """Parse one LR (RAA) record of 1270 bytes."""
    if len(raw) < LR_DATA_LEN:
        return None
    if raw[0:3] != b"RAA":
        return None

    grade_byte = chr(raw[614]) if len(raw) > 614 else " "
    grade_code = grade_byte if grade_byte.strip() else " "

    dist_raw = _ascii(raw, 616, 4)
    try:
        distance = int(dist_raw) if dist_raw.isdigit() and int(dist_raw) > 0 else None
    except ValueError:
        distance = None

    return RaceEntry(
        race_date      = _ascii(raw,   3,  8),
        venue_code     = _ascii(raw,  19,  2),
        meeting_num    = _ascii(raw,  21,  2),
        day_num        = _ascii(raw,  23,  2),
        race_num       = _ascii(raw,  25,  2),
        race_name      = _sjis( raw,  32, 180),
        condition_text = _ascii(raw, 212, 324).strip(),
        grade_code     = grade_code,
        distance       = distance,
    )


def parse_lu_record(raw: bytes) -> Optional[HorseEntry]:
    """Parse one LU (SEA) record of 553 bytes."""
    if len(raw) < LU_DATA_LEN:
        return None
    if raw[0:3] != b"SEA":
        return None

    sex_byte  = chr(raw[78]) if len(raw) > 78 and 0x30 <= raw[78] <= 0x33 else ""
    age_raw   = _ascii(raw, 82, 2)
    try:
        horse_age = int(age_raw) if age_raw.isdigit() else None
    except ValueError:
        horse_age = None

    bw_raw = _ascii(raw, 288, 3)
    try:
        body_weight = int(bw_raw) if bw_raw.isdigit() and int(bw_raw) > 0 else None
    except ValueError:
        body_weight = None

    return HorseEntry(
        race_date     = _ascii(raw,   3,  8),
        venue_code    = _ascii(raw,  19,  2),
        meeting_num   = _ascii(raw,  21,  2),
        day_num       = _ascii(raw,  23,  2),
        race_num      = _ascii(raw,  25,  2),
        gate_num      = _ascii(raw,  27,  1),
        horse_num     = _ascii(raw,  28,  2),
        blood_reg_num = _ascii(raw,  30, 10),
        horse_name    = _sjis( raw,  40, 36),
        horse_age     = horse_age,
        sex_code      = sex_byte,
        jockey_name   = _sjis( raw,  90,  8),
        jockey_code   = _ascii(raw,  98,  6),
        trainer_name  = _sjis( raw, 306, 16),
        body_weight   = body_weight,
    )


def parse_lr_file(dat_path: Path) -> list[RaceEntry]:
    data = dat_path.read_bytes()
    n = len(data) // LR_RECORD_LEN
    return [r for i in range(n)
            if (r := parse_lr_record(data[i * LR_RECORD_LEN: i * LR_RECORD_LEN + LR_DATA_LEN]))]


def parse_lu_file(dat_path: Path) -> list[HorseEntry]:
    data = dat_path.read_bytes()
    n = len(data) // LU_RECORD_LEN
    return [r for i in range(n)
            if (r := parse_lu_record(data[i * LU_RECORD_LEN: i * LU_RECORD_LEN + LU_DATA_LEN]))]


def parse_es_data_dir(es_data_year_dir: Path) -> tuple[list[RaceEntry], list[HorseEntry]]:
    """Parse all LR*.DAT and LU*.DAT files under the given year directory."""
    races: list[RaceEntry] = []
    horses: list[HorseEntry] = []

    for lr_file in sorted(es_data_year_dir.glob("LR*.DAT")):
        races.extend(parse_lr_file(lr_file))

    for lu_file in sorted(es_data_year_dir.glob("LU*.DAT")):
        horses.extend(parse_lu_file(lu_file))

    return races, horses


if __name__ == "__main__":
    import sys
    from pathlib import Path

    year_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\TFJV\ES_DATA\2026")
    races, horses = parse_es_data_dir(year_dir)

    print(f"Parsed {len(races)} races, {len(horses)} horse entries from {year_dir}")
    print()

    # Group horses by race_key for summary
    from collections import defaultdict
    horse_map: dict[str, list[HorseEntry]] = defaultdict(list)
    for h in horses:
        horse_map[h.race_key].append(h)

    race_map: dict[str, RaceEntry] = {r.race_key: r for r in races}

    printed = 0
    for key, race in sorted(race_map.items()):
        entries = horse_map.get(key, [])
        print(f"[{race.race_date}] {race.venue_name} {race.race_num}R "
              f"{race.race_name[:20]} dist={race.distance} grade={race.grade_code} "
              f"({len(entries)}頭)")
        for h in sorted(entries, key=lambda x: x.horse_num)[:3]:
            print(f"  {h.horse_num}番 [{h.horse_name}] {h.horse_age}歳{h.sex_name} "
                  f"騎手:{h.jockey_name} 調教師:{h.trainer_name}")
        if entries:
            print("  ...")
        printed += 1
        if printed >= 10:
            print(f"... (showing first 10 of {len(race_map)} races)")
            break
