"""
Deeper analysis to find distance, track type, condition, weather.
Show multiple horses from same race side-by-side.
Extended range: also check pos 291-358.
"""

from pathlib import Path
from collections import defaultdict

RECORD_LEN = 555
DATA_LEN   = 553

def load_records(dat_path):
    data = dat_path.read_bytes()
    n = len(data) // RECORD_LEN
    records = []
    for i in range(n):
        raw = data[i * RECORD_LEN: i * RECORD_LEN + DATA_LEN]
        if len(raw) < DATA_LEN or raw[0:2] != b"SE":
            continue
        race_key = raw[3:27].decode("ascii", errors="replace")
        race_date  = raw[3:11].decode("ascii")
        venue_code = raw[19:21].decode("ascii")
        race_num   = raw[25:27].decode("ascii")
        horse_num  = raw[28:30].decode("ascii")
        blood_reg  = raw[30:40].decode("ascii")
        wc         = raw[327:331].decode("ascii", errors="replace")
        records.append({
            "key": race_key, "date": race_date, "venue": venue_code,
            "race": race_num, "horse": horse_num, "blood": blood_reg,
            "wc": wc.strip(), "raw": raw
        })
    return records

def show_same_race_multirow(records, pos_start, pos_end, n_races=5, n_horses=3):
    """Show pos_start..pos_end for multiple horses in the same race."""
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r)

    race_keys = list(races.keys())[:n_races]
    print(f"\n=== pos {pos_start}-{pos_end-1}: multiple horses per race ===")
    for rk in race_keys:
        recs = races[rk][:n_horses]
        r0 = recs[0]
        print(f"\n  {r0['date']} v{r0['venue']} R{r0['race']} ({len(races[rk])} horses):")
        print(f"  {'horse':6s}  {'wc':6s}", end="")
        for p in range(pos_start, pos_end):
            print(f"  {p:3d}", end="")
        print()
        for rec in recs:
            raw = rec["raw"]
            print(f"  #{rec['horse']:4s}  {rec['wc']:6s}", end="")
            for p in range(pos_start, pos_end):
                v = raw[p]
                c = chr(v) if 0x20 <= v <= 0x7e else '.'
                print(f"  {c:>3}", end="")
            print()

def find_race_constant_any_range(records, start=0, end=553, min_pct=0.8):
    """
    Find positions that are constant within race for >= min_pct of races.
    Also report positions constant in ALL horses across ALL races (might be fixed codes).
    """
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r["raw"])

    n_races = len(races)
    results_constant = []
    results_global_const = []

    for pos in range(start, end):
        stable_races = 0
        all_vals = []
        race_vals = []
        for rk, raws in races.items():
            vals = set(r[pos] for r in raws)
            all_vals.extend(vals)
            if len(vals) == 1:
                stable_races += 1
                race_vals.append(list(vals)[0])

        pct = stable_races / n_races
        unique_all = set(all_vals)
        unique_race = set(race_vals)

        if pct >= min_pct:
            results_constant.append((pos, pct, len(unique_race), sorted(unique_race)[:15], sorted(unique_all)[:15]))

        if len(unique_all) == 1:
            results_global_const.append((pos, list(unique_all)[0]))

    return results_constant, results_global_const

def show_hex_range(records, pos_start, pos_end, n_races=8):
    """Hex dump of a range for one horse per race."""
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r)

    print(f"\n=== hex dump pos {pos_start}-{pos_end-1} ===")
    for rk in list(races.keys())[:n_races]:
        rec = races[rk][0]
        raw = rec["raw"]
        chunk = raw[pos_start:pos_end]
        ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7e else "." for b in chunk)
        hex_short = " ".join(f"{b:02x}" for b in chunk[:24])
        print(f"  {rec['date']} v{rec['venue']} R{rec['race']}: {ascii_part!r:<30} hex:{hex_short}")

def show_distinct_values(records, start=291, end=358):
    """For each pos, show all distinct values seen across all horses."""
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r["raw"])

    print(f"\n=== Distinct values per position {start}-{end-1} ===")
    for pos in range(start, end):
        all_vals = set()
        for raws in races.values():
            for raw in raws:
                all_vals.add(raw[pos])
        chars = sorted(all_vals)
        printable = [chr(c) if 0x20 <= c <= 0x7e else f"x{c:02x}" for c in chars]
        if len(chars) <= 10:  # interesting if few distinct values
            print(f"  pos {pos:3d}: {len(chars):3d} values = {printable}")

def analyze_pos_for_distance(records):
    """
    For each 4-byte window, check if all horses in a race share the same value
    AND values are in 1000-3600 range.
    """
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r["raw"])

    print("\n=== 4-byte windows: race-constant AND 1000<=v<=3600 ===")
    for pos in range(200, 553):
        valid = True
        race_values = []
        for rk, raws in races.items():
            try:
                vals = set()
                for raw in raws:
                    s = raw[pos:pos+4].decode("ascii")
                    if not s.isdigit():
                        valid = False
                        break
                    v = int(s)
                    if not (1000 <= v <= 3600):
                        valid = False
                        break
                    vals.add(v)
                if not valid:
                    break
                if len(vals) == 1:  # same for all horses in this race
                    race_values.append(list(vals)[0])
                else:
                    valid = False
                    break
            except Exception:
                valid = False
                break
        if valid:
            unique = set(race_values)
            print(f"  pos {pos:3d}-{pos+3}: {len(unique)} distinct race-vals = {sorted(unique)}")

def show_pos291_358_multirow(records, n_races=6, n_horses=4):
    """Show pos 291-305 and 322-331 for multiple horses per race."""
    ranges = [(291, 307), (322, 342)]
    for pstart, pend in ranges:
        show_same_race_multirow(records, pstart, pend, n_races=n_races, n_horses=n_horses)

def show_tail_multirow(records, n_races=5, n_horses=3):
    """Show tail region for multiple horses per race - compare if constant."""
    ranges = [(531, 553)]
    for pstart, pend in ranges:
        show_same_race_multirow(records, pstart, pend, n_races=n_races, n_horses=n_horses)

def check_1digit_race_constant(records, start=200, end=553):
    """Find 1-byte positions with values 1-8 (typical JRA code digits) that are race-constant."""
    races = defaultdict(list)
    for r in records:
        races[r["key"]].append(r["raw"])
    n_races = len(races)

    print(f"\n=== 1-byte positions with 1-8 ASCII digits, race-constant >=80% races ===")
    for pos in range(start, end):
        stable = 0
        race_vals = []
        for rk, raws in races.items():
            vals = set(raw[pos] for raw in raws)
            # All values must be ASCII '1'-'8' (0x31-0x38)
            if all(0x31 <= v <= 0x38 for v in vals):
                if len(vals) == 1:
                    stable += 1
                    race_vals.append(list(vals)[0])

        pct = stable / n_races
        if pct >= 0.75 and len(race_vals) >= int(n_races * 0.75):
            unique = set(race_vals)
            printable = [chr(c) for c in sorted(unique)]
            print(f"  pos {pos:3d}: stable_pct={pct:.0%}, {len(unique)} distinct race-vals = {printable}")

def main():
    dat_files = sorted(Path(r"C:\TFJV\SE_DATA\2026").glob("SU*.DAT"))
    print(f"Loading {len(dat_files)} files...")
    all_records = []
    for f in dat_files:
        all_records.extend(load_records(f))
    print(f"Total records: {len(all_records)}")

    races = defaultdict(list)
    for r in all_records:
        races[r["key"]].append(r)
    print(f"Total races: {len(races)}")

    # 1. Extended constant-within-race search (include 200-358)
    print("\n=== Race-constant positions (>=80%) in pos 200-552 ===")
    constants, globals_ = find_race_constant_any_range(all_records, start=200, end=553, min_pct=0.8)
    print(f"Found {len(constants)} positions constant within >=80% of races:")
    for pos, pct, n_uniq, rv_sample, av_sample in constants:
        print(f"  pos {pos:3d}: {pct:.0%} races stable, {n_uniq} distinct race-vals = {rv_sample}")
    print(f"\nFound {len(globals_)} positions with SAME value in all horses all races:")
    for pos, val in globals_[:20]:
        print(f"  pos {pos:3d}: always = {val} ({chr(val) if 0x20<=val<=0x7e else 'nonprint'})")

    # 2. Distance search (4-byte, race-constant, 1000-3600)
    analyze_pos_for_distance(all_records)

    # 3. Single-digit code positions (race-constant, value 1-8)
    check_1digit_race_constant(all_records, start=200, end=553)

    # 4. Show pos 291-331 with multiple horses
    show_pos291_358_multirow(all_records, n_races=6, n_horses=4)

    # 5. Show tail pos 531-552 with multiple horses
    show_tail_multirow(all_records, n_races=6, n_horses=4)

    # 6. Distinct values for pos 291-358
    show_distinct_values(all_records, start=291, end=358)

    # 7. Hex view of 291-331
    show_hex_range(all_records, 291, 331, n_races=10)

if __name__ == "__main__":
    main()
