"""Find 上がり3F field position by scanning tail bytes."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

data = Path(r'C:\TFJV\SE_DATA\2026\SU202613.DAT').read_bytes()
RECORD_LEN = 555

known_rank = {1:6,2:7,3:5,4:3,5:8,6:4,7:15,8:13,9:14,10:11,11:1,12:9,13:10,14:2,15:12}

print("=== bytes 359-480 as 2-char ASCII pairs ===")
print("H#  rank | 359 361 363 365 367 369 371 373 375 377 379 381 383 385 387 389 391 393 395 397 399 401 403 405 407")

for i in range(15):
    base = i * RECORD_LEN
    raw = data[base:base+553]
    if not raw.startswith(b'SE'):
        break
    horse = int(raw[28:30])
    rank = known_rank.get(horse, '?')

    parts = []
    for p in range(359, 410, 2):
        s = raw[p:p+2].decode('ascii', errors='replace')
        parts.append(s)

    line = " ".join(parts)
    print(f"H{horse:02d} r={rank:>2} | {line}")

print()
print("=== Looking for 3-digit values 330-420 (= 33.0-42.0 sec for 上がり3F) ===")
for i in range(15):
    base = i * RECORD_LEN
    raw = data[base:base+553]
    if not raw.startswith(b'SE'):
        break
    horse = int(raw[28:30])
    rank = known_rank.get(horse, '?')

    hits = []
    for p in range(340, 480):
        try:
            v = int(raw[p:p+3].decode('ascii'))
            if 330 <= v <= 420:
                hits.append(f"p{p}={v}")
        except Exception:
            pass
    print(f"H{horse:02d} r={rank:>2} | {hits}")
