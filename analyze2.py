"""Detailed structure analysis: TFJ_KISI.DAT, SK UM files, HY payout files."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'

def sjis(b):
    return b.decode(SJIS, errors='replace')

# ─────────────────────────────────────────────────────────
print("=" * 65)
print("1. TFJ_KISI.DAT - finding record length via 'KS' prefix")
print("=" * 65)
kisi = Path(r'C:\TFJV\TFJ_KISI.DAT').read_bytes()
print(f"Total: {len(kisi):,} bytes")

# Search for KS2 pattern positions
positions = [i for i in range(0, min(len(kisi), 100000))
             if kisi[i:i+2] == b'KS']
diffs = [positions[i+1] - positions[i] for i in range(min(len(positions)-1, 30))]
print(f"'KS' positions (first 10): {positions[:10]}")
print(f"Diffs between KS positions: {diffs[:20]}")

# Find the most common diff (= record length)
from collections import Counter
rlen = Counter(diffs).most_common(1)[0][0]
print(f"Record length: {rlen}")
n_recs = len(kisi) // rlen
print(f"Record count: {n_recs:,}")

# Decode first 5 records
print("\nFirst 5 jockey records:")
for i in range(min(5, n_recs)):
    rec = kisi[i*rlen:(i+1)*rlen]
    # Key fields attempt: type(3) + date(8) + code(6) + dates(8+8) + birth(8) + name(sjis)
    try:
        rtype = sjis(rec[0:3])
        date1 = sjis(rec[3:11])  # 8 chars
        code  = sjis(rec[11:17]) # 6 chars (jockey code?)
        unk1  = sjis(rec[17:25]) # 8 chars
        unk2  = sjis(rec[25:33]) # 8 chars
        birth = sjis(rec[33:41]) # 8 chars (birth date?)
        name_raw = rec[41:73]    # 32 bytes (name)
        name = sjis(name_raw).replace('　',' ').strip()
        # Look for half-width kana reading
        kana_raw = rec[73:103]
        kana = sjis(kana_raw).strip()
        print(f"  [{i}] type={rtype} code={code} birth={birth} name=[{name}] kana=[{kana[:20]}]")
    except Exception as e:
        print(f"  [{i}] ERROR: {e}")
        print(f"       hex: {rec[:40].hex()}")

# ─────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("2. UM_DATA SK file - full record analysis")
print("=" * 65)
sk = Path(r'C:\TFJV\UM_DATA\2025\SK220251.DAT').read_bytes()
rlen2 = 208
n2 = len(sk) // rlen2

# Full 208-byte hex dump of first record
rec2 = sk[:rlen2]
print(f"Full record hex dump (208 bytes):")
for i in range(0, 208, 16):
    row = rec2[i:i+16]
    hex_s = ' '.join(f'{b:02X}' for b in row)
    # Try to decode as ascii or mark non-ascii
    asc = []
    j = i
    while j < i+16 and j < 208:
        if rec2[j] >= 0x81 and j+1 < 208:
            try:
                ch = rec2[j:j+2].decode(SJIS, errors='strict')
                asc.append(ch)
                j += 2
                continue
            except:
                pass
        asc.append(chr(rec2[j]) if 32<=rec2[j]<127 else '·')
        j += 1
    print(f"  {i:03d}: {hex_s:<48}  {''.join(asc)}")

print()
# Look for non-zero non-ascii ranges (horse name might be in sjis)
print("Non-zero byte ranges (potential text fields):")
in_text = False
start = 0
for i in range(rlen2):
    if rec2[i] > 0x7E and not in_text:
        in_text = True
        start = i
    elif rec2[i] <= 0x7E and in_text:
        chunk = rec2[start:i]
        try:
            text = chunk.decode(SJIS, errors='replace')
        except:
            text = '?'
        print(f"  bytes {start:3d}-{i-1:3d}: [{text}]")
        in_text = False

# Show record 5 for comparison
print("\nRecord 5 text fields:")
rec5 = sk[4*rlen2:5*rlen2]
print(sjis(rec5[:120]))

# ─────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("3. HY payout - decode 517-byte records of HY1202613.DAT")
print("=" * 65)
hy = Path(r'C:\TFJV\HY_DATA\2026\HY1202613.DAT').read_bytes()
rlen3 = 517
n3 = len(hy) // rlen3
print(f"Records: {n3}  (72 races expected for round 13)")

# Decode records for Race 1 (venue=03 day=01 race=01)
print("\nAll payout records for Fukushima 2026-04-13 R1 (03/01/01/01):")
for i in range(n3):
    rec = hy[i*rlen3:(i+1)*rlen3]
    try:
        txt = rec.decode(SJIS, errors='replace')
    except:
        txt = rec.decode('ascii', errors='replace')
    # Parse race key
    rtype  = txt[0:3]
    rdate  = txt[3:11]
    rdate2 = txt[11:19]
    venue  = txt[19:21]
    mtg    = txt[21:23]
    day    = txt[23:25]
    race   = txt[25:27]
    if rdate == '20260413' and venue == '03' and mtg == '01' and day == '01' and race == '01':
        payload = txt[27:200]
        print(f"  R1 rec{i+1}: {payload[:120]}")
        break

# Also show records for races 1-5 to see pattern
print("\nFirst 5 records (race key + first 80 chars of payload):")
for i in range(min(5, n3)):
    rec = hy[i*rlen3:(i+1)*rlen3]
    txt = rec.decode('ascii', errors='replace')
    print(f"  rec{i+1}: date={txt[3:11]} v={txt[19:21]} r={txt[25:27]} | {txt[27:100]}")
