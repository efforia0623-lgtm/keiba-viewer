"""
CK (調教) parser for TARGET frontier JV data.

File naming:
  HC02YYYYMMDD.DAT  - JRA training records (type 0)
  HC12YYYYMMDD.DAT  - JRA training records (type 1, same format)

Record structure: 47 chars + CRLF = 49 bytes
All fields are ASCII digits.

Verified field layout (from binary analysis of HC02*.DAT files):
  [0]     : data_class    '0' or '1' (constant per file type)
  [1- 8]  : training_date YYYYMMDD
  [9-12]  : training_time HHMM (morning session clock, e.g. "0657" = 06:57)
  [13-22] : blood_reg_num 10-digit horse registration number
  [23-24] : venue_code    training venue (05=東京, 06=中山, 07=中京,
                          08=京都, 09=阪神, etc.)
  [25-34] : extra_raw     10 chars (course type, condition, unknown times)
  [35-37] : time_4f_raw   4-furlong cumulative time (tenths of seconds)
  [38-40] : time_2f_raw   2-furlong cumulative time (tenths of seconds)
  [41-43] : time_1f_a_raw 1-furlong time, first measurement (tenths)
  [44-46] : time_1f_b_raw 1-furlong time, last/final measurement (tenths)

Converting raw to seconds: value / 10.0 (e.g. "670" -> 67.0 seconds)
Zero values ("000") indicate not measured, stored as NULL.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RECORD_LEN = 49   # 47 data chars + CRLF
DATA_LEN   = 47


@dataclass
class TrainingRecord:
    training_date:  str
    training_time:  str
    blood_reg_num:  str
    venue_code:     str
    time_4f:        Optional[float]   # seconds
    time_2f:        Optional[float]
    time_1f_first:  Optional[float]
    time_1f_last:   Optional[float]
    extra_raw:      str
    source_file:    str


def _raw_to_time(raw: str) -> Optional[float]:
    """Convert 3-char tenths string to seconds, or None if zero/invalid."""
    try:
        val = int(raw)
        return val / 10.0 if val > 0 else None
    except ValueError:
        return None


def parse_file(path: Path) -> list[TrainingRecord]:
    records = []
    source = path.name
    try:
        content = path.read_bytes()
    except OSError:
        return records

    lines = content.split(b"\r\n")
    for raw_line in lines:
        if len(raw_line) < DATA_LEN:
            continue
        try:
            line = raw_line[:DATA_LEN].decode("ascii", errors="replace")
        except Exception:
            continue

        training_date  = line[1:9]
        training_time  = line[9:13]
        blood_reg_num  = line[13:23]
        venue_code     = line[23:25]
        extra_raw      = line[25:35]
        time_4f_raw    = line[35:38]
        time_2f_raw    = line[38:41]
        time_1f_a_raw  = line[41:44]
        time_1f_b_raw  = line[44:47]

        if not training_date.isdigit() or not blood_reg_num.isdigit():
            continue

        records.append(TrainingRecord(
            training_date  = training_date,
            training_time  = training_time,
            blood_reg_num  = blood_reg_num,
            venue_code     = venue_code,
            time_4f        = _raw_to_time(time_4f_raw),
            time_2f        = _raw_to_time(time_2f_raw),
            time_1f_first  = _raw_to_time(time_1f_a_raw),
            time_1f_last   = _raw_to_time(time_1f_b_raw),
            extra_raw      = extra_raw,
            source_file    = source,
        ))

    return records
