"""Find horse name in UM_DATA SK records (older year for named horses)."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'

# Use 2020 data - horses would be named then
sk_files = sorted(Path(r'C:\TFJV\UM_DATA\2020').glob('SK*.DAT'))
print(f"UM_DATA/2020 SK files: {[f.name for f in sk_files]}")

sk = sk_files[0].read_bytes()
rlen = 208
n = len(sk) // rlen
print(f"Records: {n}")

# Show full SJIS decode of first 10 records, looking for horse names
print("\nFirst 10 records - all text content:")
for i in range(min(10, n)):
    rec = sk[i*rlen:(i+1)*rlen]
    # Find all Shift-JIS text segments
    txt = rec.decode(SJIS, errors='replace')
    # Find non-space Shift-JIS runs
    # Blood reg at pos 11-20, birth at 21-28
    blood = txt[3:13]   # 10 bytes at pos 3-12
    date1 = txt[13:21]  # 8 bytes
    birth = txt[21:29]  # 8 bytes
    # Scan for Shift-JIS kanji/kana (non-ASCII)
    sjis_runs = []
    j = 0
    while j < rlen:
        if rec[j] >= 0x80:
            start = j
            run = b''
            while j < rlen and rec[j] >= 0x80:
                run += rec[j:j+1]
                j += 1
            text = run.decode(SJIS, errors='replace').replace('　', ' ').strip()
            if text:
                sjis_runs.append(f"p{start}:[{text}]")
        else:
            j += 1
    print(f"  R{i+1}: blood={blood} birth={birth} sjis={sjis_runs}")

print()
# Look at one specific record in detail
print("Record 1 detailed - bytes 0-207:")
rec = sk[:208]
for i in range(0, 208, 8):
    raw = rec[i:i+8]
    hex_s = ' '.join(f'{b:02X}' for b in raw)
    asc = ''.join(chr(b) if 32<=b<127 else '·' for b in raw)
    print(f"  {i:3d}-{i+7:3d}: {hex_s}  {asc}")

# HY: search for known 単勝 amount in Race 1
print("\n=== HY: search for 590 (単勝 payout) in R1 record ===")
hy = Path(r'C:\TFJV\HY_DATA\2026\HY1202613.DAT').read_bytes()
rlen3 = 517
rec_r1 = hy[:rlen3]  # R1 is record 0
txt_r1 = rec_r1.decode('ascii', errors='replace')
# Search for "0590" and "590"
for target in ['0590', '590', '00059', '000590']:
    idx = txt_r1.find(target)
    if idx >= 0:
        print(f"  Found '{target}' at pos {idx}: ...{txt_r1[max(0,idx-10):idx+20]}...")

print("\nHY R1 record - every 6 bytes from payload (pos 27):")
payload = rec_r1[27:]
print(f"  Payload length: {len(payload)}")
# Print as 6-byte groups
groups = []
for i in range(0, min(len(payload), 300), 6):
    g = payload[i:i+6].decode('ascii', errors='?')
    groups.append(f"p{27+i}:{g}")
for i in range(0, len(groups), 6):
    print(f"  {' | '.join(groups[i:i+6])}")
