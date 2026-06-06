# -*- coding: utf-8 -*-
"""Decode RA records from ES_DATA and WF records."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path

def decode_sjis(raw):
    try:
        return raw.decode('shift_jis', errors='replace').replace('　', ' ').strip()
    except:
        return '?'

# Decode ES_DATA LR files
print("=== ES_DATA LR records ===")
p = Path(r'C:\TFJV\ES_DATA\2026')
files = sorted(p.glob('LR*.DAT'))[:8]
for f in files:
    data = f.read_bytes()
    RECLEN = 212
    if len(data) < RECLEN: continue
    rec = data[:RECLEN]
    date = rec[3:11].decode('ascii', errors='replace')
    pos19_29 = rec[19:30].decode('ascii', errors='replace')
    name = decode_sjis(rec[33:73])
    # Find ASCII text
    ascii_parts = []
    i = 70
    while i < 212:
        if 0x20 <= rec[i] <= 0x7e:
            j = i
            while j < 212 and 0x20 <= rec[j] <= 0x7e:
                j += 1
            part = rec[i:j].decode('ascii', errors='replace').strip()
            if len(part) > 5:
                ascii_parts.append(f'pos{i}:{part[:40]}')
            i = j
        else:
            i += 1
    print(f"{f.name}: date={date} pos19-28={pos19_29!r}")
    print(f"  name={name!r}")
    print(f"  english={ascii_parts[:3]}")
    print()

# WF file
print("=== WF file ===")
wf = Path(r'C:\TFJV\W5_DATA\2026\WF260104.DAT').read_bytes()[:7215]
print(f"len={len(wf)}")
print("Non-zero bytes at pos 19-200:")
for i in range(19, 200):
    b = wf[i]
    if b != 48:  # not '0'
        c = chr(b) if 0x20 <= b <= 0x7e else f'x{b:02x}'
        print(f"  pos {i:3d}: {b:3d}  {c}")

print("\nChunks pos 19-100:")
for start in range(19, 100, 8):
    chunk = wf[start:start+8]
    asc = ''.join(chr(b) if 0x20<=b<=0x7e else '.' for b in chunk)
    print(f"  {start:3d}: {asc}  {' '.join(f'{b:02x}' for b in chunk)}")
