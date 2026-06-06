"""
SU (成績-馬毎レース情報) parser for TARGET frontier JV data.

File naming: SU{YEAR}{ROUND}.DAT
Record structure: 555 bytes fixed-length (553 data bytes + CRLF)
Encoding: Shift-JIS mixed with ASCII numeric fields

Verified field layout (from binary analysis of SU202613.DAT, 2026/4/13 Fukushima):

  0-  1  "SE"   record identifier
  2        "7"   data type
  3- 10  race_date        YYYYMMDD
 11- 18  created_date     YYYYMMDD
 19- 20  venue_code       開催場コード
 21- 22  meeting_num      開催回次
 23- 24  day_num          開催日次
 25- 26  race_num         レース番号
 27      gate_num         枠番 (1 byte ASCII digit)
 28- 29  horse_num        馬番
 30- 39  blood_reg_num    血統登録番号 (10 ASCII digits)
 40- 75  horse_name       馬名 (36 bytes Shift-JIS, 18 full-width chars)
 76- 89  [14-byte code block]
   78- 79   code_78        unknown 2-byte code
   80- 81   horse_age      馬齢 (2 ASCII digits)
   82- 83   code_82        unknown (constant per race?)
   84- 85   sex_code       性別コード (10=牡, 20=牝, 30=騸)
   86- 87   coat_code      毛色コード
   88- 89   code_88        unknown
 90- 97  jockey_name      騎手名 (8 bytes Shift-JIS, 4 full-width chars)
 98-103  jockey_code      騎手コード (6 ASCII digits)
104-167  owner_name       馬主名 (64 bytes Shift-JIS, 32 full-width chars)
168-279  silks_desc       服色 (112 bytes Shift-JIS)
280-287  field_280        (8 bytes, always blank)
288-290  horse_weight     馬体重 kg (3 ASCII digits, "   " if unknown)
291-305  field_291        (15 bytes, unknown - possibly odds/pool data)
306-321  trainer_name     調教師名 (16 bytes Shift-JIS, 8 full-width chars)
322-326  field_322        (5 bytes, unknown)
327-330  weight_change    体重増減 (+/-XXX or "    " if unknown)
331      (constant '0')
332      finish_tens      着順 tens digit (ASCII)
333      finish_ones      着順 ones digit (ASCII)
334      (duplicate of 332)
335      (duplicate of 333)
336-337  (constant "00")
338      time_min         走破タイム 分 (ASCII digit)
339-340  time_sec         走破タイム 秒 (2 ASCII digits)
341      time_tenth       走破タイム 1/10秒 (ASCII digit)
342-350  finish_margin    着差 (9 bytes, right-padded with spaces)
351-352  corner1          1コーナー通過順位 (2 ASCII digits)
353-354  corner2          2コーナー通過順位
355-356  corner3          3コーナー通過順位
357-358  corner4          4コーナー通過順位
359-362  field_359        (4 bytes, unknown)
363-364  popularity       人気 (2 ASCII digits, 1=1番人気)
365-388  field_365        (24 bytes, includes payout data for money finishers)
389      (constant '0' - leading zero of agari field)
390-392  agari_3f_raw     上がり3ハロンタイム (3 ASCII digits, SST in tenths: 379→37.9s)
393-402  winner_blood_reg 勝ち馬血統登録番号 (10 bytes, for reference)
403-438  winner_name      勝ち馬馬名 (36 bytes Shift-JIS)
439-530  [blank: 2着・3着馬名参照フィールド (未使用)]
531-534  [weight_change repeat or other horse field]
535      (constant '0' prefix)
536      (constant '3' - fixed code)
537      track_type_code  コース種別 (1=芝, 2=ダート, 3=障害; race-constant)
538      dist_class_code  距離クラス (0-5; race-constant, maps to standard JRA distance)
539-552  [horse-level fields, not yet decoded]

Distance mapping (dist_class_code per track_type_code):
  芝 (1): 0→1000m, 1→1200m, 2→1400m, 3→1600m, 4→1800m, 5→2000m+
  ダート (2): 0→~1800m, 1→~2100m, 2→~2300m, 3→~2400m, 4→~2600m
  障害 (3): 0→~2500m, 1→~2600m, 2→~2700m, 3→~2800m, 4→~3000m, 5→~3200m
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

RECORD_LEN = 555
DATA_LEN   = 553   # excluding CRLF

SJIS       = "shift_jis"
FULL_SPACE = "　"   # 0x8140

VENUE_NAMES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}

SEX_MAP = {"10": "牡", "20": "牝", "30": "騸", "1": "牡", "2": "牝", "3": "騸"}

TRACK_TYPE_MAP = {
    "1": "芝", "2": "ダート", "3": "障害",
}

# (track_type_code, dist_class_code) → approximate distance in meters
# 芝: 0=1000m, 1=1200m, 2=1400m, 3=1600m, 4=1800m, 5=2000m+
# ダート: venue-dependent (e.g. Fukushima=1700m, Nakayama=1800m, Kyoto=2000m at class 0)
# 障害: approximate
DISTANCE_MAP: dict[tuple[str, str], int] = {
    ("1", "0"): 1000,
    ("1", "1"): 1200,
    ("1", "2"): 1400,
    ("1", "3"): 1600,
    ("1", "4"): 1800,
    ("1", "5"): 2000,
    ("2", "0"): 1800,
    ("2", "1"): 2100,
    ("2", "2"): 2300,
    ("2", "3"): 2400,
    ("2", "4"): 2600,
    ("3", "0"): 2500,
    ("3", "1"): 2600,
    ("3", "2"): 2700,
    ("3", "3"): 2800,
    ("3", "4"): 3000,
    ("3", "5"): 3200,
    ("4", "3"): 3600,
    ("5", "0"): 4250,
    ("0", "5"): 800,
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


def _int(raw: bytes, start: int, length: int) -> Optional[int]:
    s = raw[start:start + length].decode("ascii", errors="replace").strip()
    try:
        return int(s) if s else None
    except ValueError:
        return None


@dataclass
class HorseResult:
    # ── Race key ──────────────────────────────────────────────────────────
    race_date   : str          # YYYYMMDD
    venue_code  : str          # 2-digit
    meeting_num : str
    day_num     : str
    race_num    : str

    # ── Horse entry ───────────────────────────────────────────────────────
    gate_num      : str
    horse_num     : str
    blood_reg_num : str
    horse_name    : str

    # ── Horse attributes ──────────────────────────────────────────────────
    horse_age  : str
    sex_code   : str
    coat_code  : str

    # ── People ────────────────────────────────────────────────────────────
    jockey_name : str
    jockey_code : str
    trainer_name: str
    owner_name  : str

    # ── Appearance ────────────────────────────────────────────────────────
    silks_desc : str

    # ── Race-day condition ────────────────────────────────────────────────
    horse_weight  : Optional[int]   # kg
    weight_change : str             # "+002", "-018", "    " etc.

    # ── Race result ───────────────────────────────────────────────────────
    finish_pos    : Optional[int]   # 着順 (1-18; None if 取消/除外)
    race_time     : str             # "M:SS.T" e.g. "1:45.9"
    finish_margin : str             # 着差 e.g. "K", "1", "312" etc.
    popularity    : Optional[int]   # 人気 (betting rank)

    # ── 4-corner passage positions ────────────────────────────────────────
    corner1 : Optional[int]
    corner2 : Optional[int]
    corner3 : Optional[int]
    corner4 : Optional[int]

    # ── 上がり3ハロン ─────────────────────────────────────────────────────────
    agari_3f : Optional[float]  # 上がり3F (seconds, e.g. 37.9)

    # ── Winner reference (stored in every horse's record for this race) ───
    winner_blood_reg : str
    winner_name      : str

    # ── Course / distance (pos 537-538, race-level constants) ────────────
    track_type  : str            # '芝', 'ダート', '障害', '' if unknown
    dist_class  : str            # '0'-'5' raw code; maps to standard distance
    distance    : Optional[int]  # approximate meters from (track_type, dist_class)

    # ── Raw tail (pos 439-552) for future analysis ────────────────────────
    tail_raw : str   # hex-encoded

    # ── Derived ───────────────────────────────────────────────────────────
    venue_name : str = field(init=False)
    sex_name   : str = field(init=False)

    def __post_init__(self):
        self.venue_name = VENUE_NAMES.get(self.venue_code, self.venue_code)
        self.sex_name   = SEX_MAP.get(self.sex_code, self.sex_code)

    @property
    def race_key(self) -> str:
        return f"{self.race_date}{self.venue_code}{self.meeting_num}{self.day_num}{self.race_num}"

    @property
    def time_seconds(self) -> Optional[float]:
        """Race time as total seconds (float)."""
        if not self.race_time or ':' not in self.race_time:
            return None
        try:
            m, rest = self.race_time.split(':')
            s, t = rest.split('.')
            return int(m) * 60 + int(s) + int(t) / 10
        except Exception:
            return None


def _parse_finish_pos(raw: bytes) -> Optional[int]:
    """着順: tens at byte 332, ones at byte 333."""
    try:
        tens = raw[332] - ord('0')
        ones = raw[333] - ord('0')
        if not (0 <= tens <= 1 and 0 <= ones <= 9):
            return None
        pos = tens * 10 + ones
        return pos if pos > 0 else None
    except Exception:
        return None


def _parse_time(raw: bytes) -> str:
    """走破タイム: bytes 338 (min), 339-340 (sec), 341 (tenth)."""
    try:
        m  = chr(raw[338])
        ss = raw[339:341].decode("ascii")
        t  = chr(raw[341])
        if m.isdigit() and ss.isdigit() and t.isdigit():
            return f"{m}:{ss}.{t}"
    except Exception:
        pass
    return ""


def _parse_corner(raw: bytes, start: int) -> Optional[int]:
    try:
        v = int(raw[start:start + 2].decode("ascii"))
        return v if v > 0 else None
    except Exception:
        return None


def _parse_agari(raw: bytes) -> Optional[float]:
    """上がり3F: bytes 390-392 as SST (tenths of seconds). e.g. '379' → 37.9s."""
    try:
        s = raw[390:393].decode("ascii")
        if s.isdigit():
            return int(s) / 10
    except Exception:
        pass
    return None


def _parse_course(raw: bytes) -> tuple[str, str, Optional[int]]:
    """Extract track_type, dist_class, distance from pos 537-538."""
    tc = chr(raw[537]) if len(raw) > 537 and 0x30 <= raw[537] <= 0x39 else ""
    dc = chr(raw[538]) if len(raw) > 538 and 0x30 <= raw[538] <= 0x39 else ""
    track_type = TRACK_TYPE_MAP.get(tc, "")
    distance   = DISTANCE_MAP.get((tc, dc), None)
    return track_type, dc, distance


def parse_record(raw: bytes) -> Optional[HorseResult]:
    if len(raw) < DATA_LEN:
        return None
    if raw[0:2] != b"SE":
        return None

    hw_str = _ascii(raw, 288, 3)
    horse_weight = int(hw_str) if hw_str.isdigit() else None

    wc = raw[327:331].decode("ascii", errors="replace")
    weight_change = wc if wc.strip() else ""

    track_type, dist_class, distance = _parse_course(raw)

    return HorseResult(
        race_date        = _ascii(raw,   3,  8),
        venue_code       = _ascii(raw,  19,  2),
        meeting_num      = _ascii(raw,  21,  2),
        day_num          = _ascii(raw,  23,  2),
        race_num         = _ascii(raw,  25,  2),
        gate_num         = _ascii(raw,  27,  1),
        horse_num        = _ascii(raw,  28,  2),
        blood_reg_num    = _ascii(raw,  30, 10),
        horse_name       = _sjis( raw,  40, 36),
        horse_age        = _ascii(raw,  80,  2),
        sex_code         = _ascii(raw,  84,  2),
        coat_code        = _ascii(raw,  86,  2),
        jockey_name      = _sjis( raw,  90,  8),
        jockey_code      = _ascii(raw,  98,  6),
        trainer_name     = _sjis( raw, 306, 16),
        owner_name       = _sjis( raw, 104, 64),
        silks_desc       = _sjis( raw, 168, 112),
        horse_weight     = horse_weight,
        weight_change    = weight_change,
        finish_pos       = _parse_finish_pos(raw),
        race_time        = _parse_time(raw),
        finish_margin    = raw[342:351].decode("ascii", errors="replace").rstrip(),
        popularity       = _int(raw, 363, 2),
        corner1          = _parse_corner(raw, 351),
        corner2          = _parse_corner(raw, 353),
        corner3          = _parse_corner(raw, 355),
        corner4          = _parse_corner(raw, 357),
        agari_3f         = _parse_agari(raw),
        winner_blood_reg = _ascii(raw, 393, 10),
        winner_name      = _sjis( raw, 403, 36),
        track_type       = track_type,
        dist_class       = dist_class,
        distance         = distance,
        tail_raw         = raw[439:553].hex(),
    )


def parse_file(dat_path: Path) -> list[HorseResult]:
    data = dat_path.read_bytes()
    n    = len(data) // RECORD_LEN
    return [r for i in range(n)
            if (r := parse_record(data[i * RECORD_LEN: i * RECORD_LEN + DATA_LEN]))]


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
           Path(r"C:\TFJV\SE_DATA\2026\SU202613.DAT")
    records = parse_file(path)
    print(f"Parsed {len(records)} records from {path.name}")
    for r in records[:5]:
        wc = f"({r.weight_change})" if r.weight_change.strip() else ""
        print(f"  {r.race_date} {r.venue_name} R{r.race_num} "
              f"枠{r.gate_num} 馬{r.horse_num} [{r.horse_name}] "
              f"着{r.finish_pos} {r.race_time} 差:{r.finish_margin!r} "
              f"C:{r.corner1}-{r.corner2}-{r.corner3}-{r.corner4} "
              f"人気{r.popularity} 体重{r.horse_weight}{wc}kg")
