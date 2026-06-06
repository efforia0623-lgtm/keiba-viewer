"""
Field analysis tool: prints specific byte ranges across many records
to help identify unknown fields by pattern matching.

Usage:
    python -m src.parser.analyze_fields [dat_file] [start_pos] [length]
"""

import sys
from pathlib import Path

SJIS = "shift_jis"
RECORD_LEN = 555
DATA_LEN = 553
FULL_SPACE = "　"


def decode_field(raw: bytes, start: int, length: int) -> str:
    chunk = raw[start:start + length]
    try:
        text = chunk.decode(SJIS, errors="replace").replace(FULL_SPACE, "_")
        return text
    except Exception:
        return chunk.hex()


def analyze(dat_path: Path, start: int, length: int, n_records: int = 30) -> None:
    data = dat_path.read_bytes()
    total = len(data) // RECORD_LEN

    print(f"File: {dat_path.name}  |  {total} records  |  "
          f"Showing bytes [{start}:{start+length}] for first {n_records} records\n")
    print(f"{'Rec':>4}  {'Gate':>4}  {'Horse':>5}  {'Field':>{max(length,6)}}")
    print("-" * 60)

    for i in range(min(n_records, total)):
        base = i * RECORD_LEN
        raw = data[base:base + DATA_LEN]

        gate  = chr(raw[27])
        horse = raw[28:30].decode("ascii", errors="?")
        field = decode_field(raw, start, length)
        print(f"{i+1:>4}  {gate:>4}  {horse:>5}  {field}")


if __name__ == "__main__":
    path  = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\TFJV\SE_DATA\2026\SU202613.DAT")
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 280
    lng   = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    n     = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    analyze(path, start, lng, n)
