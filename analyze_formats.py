"""Detailed binary analysis of UM/HY/KT data formats."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'

def hex_dump(data, start=0, length=120, label=''):
    chunk = data[start:start+length]
    if label:
        print(f"\n--- {label} ---")
    for i in range(0, len(chunk), 16):
        row = chunk[i:i+16]
        hex_s = ' '.join(f'{b:02X}' for b in row)
        asc_s = ''.join(chr(b) if 32<=b<127 else '.' for b in row)
        print(f"  {start+i:04d}: {hex_s:<48}  {asc_s}")

def find_record_len(data, max_len=600):
    """Find record length by looking for repeating 2-byte prefix."""
    prefix = data[:2]
    for rlen in range(8, max_len+1):
        if len(data) % rlen == 0:
            # Check if records 2,3,4 also start with same prefix
            ok = all(data[r*rlen:r*rlen+2] == prefix
                     for r in range(1, min(10, len(data)//rlen)))
            if ok:
                return rlen
    return None

# ─────────────────────────────────────────────────────────
print("=" * 70)
print("1. TFJ_KISI.DAT (騎手マスタ)")
print("=" * 70)
p = Path(r'C:\TFJV\TFJ_KISI.DAT')
data = p.read_bytes()
print(f"Total: {len(data):,} bytes")
rlen = find_record_len(data)
print(f"Record length: {rlen}")
if rlen:
    print(f"Record count: {len(data)//rlen:,}")
    hex_dump(data, 0, min(rlen*2, 240), 'Records 1-2')
    try:
        print("Rec1 SJIS:", data[:rlen].decode(SJIS, errors='replace'))
    except:
        pass

# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("2. UM_DATA SK file (馬マスタ)")
print("=" * 70)
p2 = Path(r'C:\TFJV\UM_DATA\2025\SK220251.DAT')
data2 = p2.read_bytes()
print(f"Total: {len(data2):,} bytes")
rlen2 = find_record_len(data2, 1000)
print(f"Record length: {rlen2}")
if rlen2:
    print(f"Record count: {len(data2)//rlen2:,}")
    hex_dump(data2, 0, min(rlen2, 160), 'Record 1')
    try:
        print("Rec1 SJIS:", data2[:rlen2].decode(SJIS, errors='replace')[:200])
    except:
        pass

# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("3. HY1202613.DAT (払戻データ 2026 R13)")
print("=" * 70)
p3 = Path(r'C:\TFJV\HY_DATA\2026\HY1202613.DAT')
data3 = p3.read_bytes()
print(f"Total: {len(data3):,} bytes")
rlen3 = find_record_len(data3)
print(f"Record length: {rlen3}")
if rlen3:
    n = len(data3) // rlen3
    print(f"Record count: {n:,}")
    # Show first 6 records
    for i in range(min(6, n)):
        rec = data3[i*rlen3:(i+1)*rlen3]
        try:
            txt = rec.decode(SJIS, errors='replace')
        except:
            txt = rec.decode('ascii', errors='replace')
        print(f"  Rec{i+1}: {txt[:90]}")

# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("4. KT2_26.DAT (騎手成績 2026?)")
print("=" * 70)
p4 = Path(r'C:\TFJV\KT_DATA\KT2_26.DAT')
if not p4.exists():
    p4 = Path(r'C:\TFJV\KT_DATA\KT2_10.DAT')
data4 = p4.read_bytes()
print(f"File: {p4.name}, Total: {len(data4):,} bytes")
rlen4 = find_record_len(data4, 500)
print(f"Record length: {rlen4}")
if rlen4:
    print(f"Record count: {len(data4)//rlen4:,}")
    try:
        print("Rec1 SJIS:", data4[:rlen4].decode(SJIS, errors='replace')[:200])
    except:
        pass
    hex_dump(data4, 0, min(rlen4, 120), f'Record 1 of {p4.name}')
