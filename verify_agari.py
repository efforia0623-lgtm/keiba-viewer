"""Cross-race verification of 上がり3F position at bytes 390-392."""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

RECORD_LEN = 555
conn = sqlite3.connect(r'data\keiba.db')

# Verify against DB: all horses in 2 different races
test_cases = [
    ('20260413', '03', '01', '01', '01',  # Fukushima R1
     Path(r'C:\TFJV\SE_DATA\2026\SU202613.DAT')),
    ('20260413', '03', '01', '01', '06',  # Fukushima R6
     Path(r'C:\TFJV\SE_DATA\2026\SU202613.DAT')),
]

for race_date, venue, mtg, day, race_num, dat_path in test_cases:
    data = dat_path.read_bytes()
    n = len(data) // RECORD_LEN

    print(f"\n=== {race_date} 会場{venue} R{race_num} ===")
    print(f"{'H#':>3} {'name':<14} {'rank':>4} {'time':<8} {'agari390':>9}sec")

    for i in range(n):
        raw = data[i*RECORD_LEN:i*RECORD_LEN+553]
        if not raw.startswith(b'SE'):
            continue
        rd   = raw[3:11].decode('ascii')
        vc   = raw[19:21].decode('ascii')
        mn   = raw[21:23].decode('ascii')
        dn   = raw[23:25].decode('ascii')
        rn   = raw[25:27].decode('ascii')
        if rd != race_date or vc != venue or mn != mtg or dn != day or rn != race_num:
            continue

        horse = raw[28:30].decode('ascii')
        name  = raw[40:76].decode('shift_jis', errors='replace').replace('　',' ').strip()[:12]
        tens  = raw[332] - ord('0')
        ones  = raw[333] - ord('0')
        rank  = tens*10 + ones if (0 <= tens <= 1 and 0 <= ones <= 9) else 99
        m, ss, t = chr(raw[338]), raw[339:341].decode('ascii'), chr(raw[341])
        time_str = f"{m}:{ss}.{t}"

        agari_raw = raw[390:393].decode('ascii', errors='replace')
        try:
            agari = int(agari_raw) / 10
        except ValueError:
            agari = None

        print(f"{horse:>3} {name:<14} {rank:>4}着 {time_str:<8} {agari_raw}→{agari:5.1f}s")

conn.close()
print("\nVerification complete.")
