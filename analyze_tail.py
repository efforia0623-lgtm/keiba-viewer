"""
Binary analysis of SU*.DAT tail_raw (pos 439-552) plus unknown fields.
Strategy: find bytes that are CONSTANT within a race but VARY between races
→ those are race-level fields (distance, track type, condition, weather).
"""

import sys
from pathlib import Path
from collections import defaultdict

RECORD_LEN = 555
DATA_LEN   = 553

def load_records(dat_path: Path):
    data = dat_path.read_bytes()
    n = len(data) // RECORD_LEN
    records = []
    for i in range(n):
        raw = data[i * RECORD_LEN: i * RECORD_LEN + DATA_LEN]
        if len(raw) < DATA_LEN or raw[0:2] != b"SE":
            continue
        race_key = raw[3:27].decode("ascii", errors="replace")  # date+venue+meeting+day+race
        race_date  = raw[3:11].decode("ascii")
        venue_code = raw[19:21].decode("ascii")
        race_num   = raw[25:27].decode("ascii")
        records.append((race_key, race_date, venue_code, race_num, raw))
    return records

def analyze_constant_within_race(records, start=0, end=553):
    """Find byte positions that are constant within each race but vary across races."""
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append(raw)

    # For each pos, compute: varies_within_race, varies_across_races
    n_races = len(races)
    constant_within = []  # pos where ALL races have uniform value across horses

    for pos in range(start, end):
        within_stable = 0
        values_per_race = []
        for rk, raws in races.items():
            vals = set(r[pos] for r in raws)
            if len(vals) == 1:
                within_stable += 1
                values_per_race.append(list(vals)[0])
            else:
                values_per_race = None
                break

        if values_per_race is not None and within_stable == n_races:
            # constant within every race; check if it varies across races
            unique_across = len(set(values_per_race))
            if unique_across > 1:
                constant_within.append((pos, unique_across, values_per_race[:10]))

    return constant_within

def show_race_bytes(records, pos_list, n_races=8):
    """Show specific byte positions for first N races."""
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append((rd, vc, rn, raw))

    race_keys = list(races.keys())[:n_races]

    print(f"\n{'Race key':<28}", end="")
    for p in pos_list:
        print(f"  p{p:03d}", end="")
    print()
    print("-" * (28 + len(pos_list) * 7))

    for rk in race_keys:
        raws = races[rk]
        rd, vc, rn, raw0 = raws[0]
        print(f"{rd} v{vc} R{rn} ({len(raws):2d}hd)", end="")
        for p in pos_list:
            v = raw0[p]
            c = chr(v) if 0x20 <= v <= 0x7e else '.'
            print(f"  {v:3d}{c}", end="")
        print()

def find_distance_candidate(records):
    """
    Distance is 1000-3600. Look for 4-byte ASCII numeric groups
    in the range within tail or unknown fields.
    """
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append(raw)

    # Check all 4-byte windows for ASCII 4-digit number in [1000,3600]
    candidates = []
    for start_pos in range(330, 553):
        valid_for_all = True
        values = []
        for rk, raws in races.items():
            raw = raws[0]
            chunk = raw[start_pos:start_pos+4]
            try:
                s = chunk.decode("ascii")
                if s.isdigit():
                    v = int(s)
                    if 1000 <= v <= 3600:
                        values.append(v)
                    else:
                        valid_for_all = False
                        break
                else:
                    valid_for_all = False
                    break
            except Exception:
                valid_for_all = False
                break

        if valid_for_all and len(values) == len(races):
            unique = set(values)
            candidates.append((start_pos, sorted(unique), values[:10]))

    return candidates

def show_tail_hex(records, n_races=6):
    """Show hex dump of tail region for one horse per race."""
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append((rd, vc, rn, raw))

    race_keys = list(races.keys())[:n_races]
    print("\n=== Tail region hex dump (pos 439-553) ===")
    for rk in race_keys:
        rd, vc, rn, raw = races[rk][0]
        tail = raw[439:553]
        print(f"\n{rd} v{vc} R{rn}:")
        for offset in range(0, len(tail), 16):
            chunk = tail[offset:offset+16]
            hex_part  = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7e else "." for b in chunk)
            print(f"  {439+offset:3d}: {hex_part:<47}  {ascii_part}")

def show_unknown_fields_hex(records, n_races=8):
    """Show hex of the still-unknown fields across records."""
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append((rd, vc, rn, raw))

    race_keys = list(races.keys())[:n_races]

    # Show field_359-362, field_365-388, and start of tail_raw
    regions = [
        (359, 363, "field_359-362"),
        (363, 365, "popularity"),
        (365, 389, "field_365-388"),
        (389, 393, "agari_prefix+agari"),
        (439, 470, "tail[0:31]"),
        (470, 510, "tail[31:71]"),
        (510, 553, "tail[71:114]"),
    ]

    for start, end, label in regions:
        print(f"\n=== {label} (pos {start}-{end-1}) ===")
        print(f"{'Race':<28}", end="")
        for p in range(start, end):
            print(f" {p:3d}", end="")
        print()
        for rk in race_keys:
            raws = races[rk]
            rd, vc, rn, raw = raws[0]
            print(f"{rd} v{vc} R{rn}", end="")
            for p in range(start, end):
                v = raw[p]
                c = chr(v) if 0x20 <= v <= 0x7e else '?'
                print(f" {c:>3}", end="")
            print(f"  ({len(raws)}hd)")

def show_pos365_detail(records, n_races=12):
    """Detailed look at pos 365-438 with known race info."""
    races = defaultdict(list)
    for rk, rd, vc, rn, raw in records:
        races[rk].append((rd, vc, rn, raw))

    race_keys = list(races.keys())[:n_races]
    print("\n=== pos 365-438 detail (one horse per race) ===")
    for rk in race_keys:
        rd, vc, rn, raw = races[rk][0]
        chunk = raw[365:439]
        hex_part  = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7e else "." for b in chunk)
        print(f"{rd} v{vc} R{rn}: {ascii_part}")
        print(f"  hex: {' '.join(f'{b:02x}' for b in chunk[:32])}")

def main():
    # Use all 2026 files for richer cross-race variation
    dat_files = sorted(Path(r"C:\TFJV\SE_DATA\2026").glob("SU*.DAT"))
    if not dat_files:
        print("No DAT files found!")
        return

    print(f"Loading {len(dat_files)} files...")
    all_records = []
    for f in dat_files[:5]:  # first 5 files = ~100 races
        all_records.extend(load_records(f))

    print(f"Total records: {len(all_records)}")
    races = defaultdict(list)
    for rk, *_ in all_records:
        races[rk].append(1)
    print(f"Total races: {len(races)}")

    # 1. Find bytes constant within race but varying across races
    print("\n=== Bytes constant within a race but varying across races (pos 359-552) ===")
    candidates = analyze_constant_within_race(all_records, start=359, end=553)
    print(f"Found {len(candidates)} candidate positions:")
    for pos, n_unique, sample_vals in candidates[:40]:
        print(f"  pos {pos:3d}: {n_unique} distinct values, sample={sample_vals}")

    # 2. Look for 4-byte ASCII distance candidates
    print("\n=== 4-byte ASCII distance candidates (1000-3600m) ===")
    dist_cands = find_distance_candidate(all_records)
    for pos, unique_vals, samples in dist_cands:
        print(f"  pos {pos:3d}-{pos+3}: unique={unique_vals}, samples={samples}")

    # 3. Show tail hex for first few races
    show_tail_hex(all_records, n_races=8)

    # 4. Show character view of unknown regions
    show_unknown_fields_hex(all_records, n_races=10)

    # 5. Detailed view of pos 365-438
    show_pos365_detail(all_records, n_races=12)

if __name__ == "__main__":
    main()
