"""Analyze KT2_XX.DAT files - likely pedigree/horse master with internal IDs."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
TFJV = Path(r'C:\TFJV')

# KT2_10.DAT full record structure analysis
kt2 = (TFJV / 'KT_DATA/KT2_10.DAT').read_bytes()
RLEN = 251   # confirmed from earlier analysis
n = len(kt2) // RLEN
print(f"KT2_10.DAT: {len(kt2):,} bytes, {n} records (rlen={RLEN})")

# Full hex dump of record 1
print("\n=== Record 1 full hex dump ===")
rec = kt2[:RLEN]
for i in range(0, RLEN, 16):
    row = rec[i:i+16]
    hex_s = ' '.join(f'{b:02X}' for b in row)
    asc = []
    j = i
    while j < i+16 and j < RLEN:
        b = rec[j]
        if b >= 0x81 and j+1 < RLEN:
            try:
                ch = rec[j:j+2].decode(SJIS, errors='strict')
                asc.append(ch); j += 2; continue
            except: pass
        asc.append(chr(b) if 32<=b<127 else '·')
        j += 1
    print(f"  {i:03d}: {hex_s:<48}  {''.join(asc)}")

# Show first 10 records fully decoded
print("\n=== First 10 records (decoded) ===")
for i in range(min(10, n)):
    rec = kt2[i*RLEN:(i+1)*RLEN]
    txt = rec.decode(SJIS, errors='replace')
    # Key fields attempt
    rtype = txt[0:3]
    date  = txt[3:11]        # 8 bytes
    uid   = txt[11:21]       # 10 bytes (internal ID?)
    zeros = txt[21:41]       # 20 bytes (usually zeros?)
    name_raw = rec[41:73]    # 32 bytes (name in SJIS)
    name = name_raw.decode(SJIS, errors='replace').replace('　',' ').strip()
    tail  = txt[73:120]      # remaining
    # Find 10-digit IDs in tail
    ids_in_tail = [tail[j:j+10] for j in range(0, len(tail)-10, 1)
                   if tail[j:j+10].isdigit()]
    unique_ids = list(dict.fromkeys(ids_in_tail))[:4]
    print(f"  [{i}] type={rtype} date={date} uid={uid} name=[{name[:20]}] tail_ids={unique_ids}")

# Search for known pedigree IDs
print("\n=== Search for pedigree IDs across ALL KT2 files ===")
target_ids = ['1120002295', '1120002084', '1120002430', '1220066273', '1220063948']
for kt_file in sorted((TFJV / 'KT_DATA').glob('KT2_*.DAT')):
    data = kt_file.read_bytes()
    n2 = len(data) // RLEN
    for tid in target_ids:
        target_bytes = tid.encode('ascii')
        if target_bytes in data:
            idx = data.index(target_bytes)
            rec_idx = idx // RLEN
            rec = data[rec_idx*RLEN:(rec_idx+1)*RLEN]
            txt = rec.decode(SJIS, errors='replace')
            uid = txt[11:21]
            name = rec[41:73].decode(SJIS, errors='replace').replace('　',' ').strip()
            print(f"  {kt_file.name}: uid={uid} name=[{name}]  (searched: {tid})")
            break
    else:
        continue
    break  # show only first found file

# Build a comprehensive UID → name map from all KT2 files
print("\n=== Building UID→name map from all KT2 files ===")
uid_name = {}
for kt_file in sorted((TFJV / 'KT_DATA').glob('KT2_*.DAT')):
    data = kt_file.read_bytes()
    n2 = len(data) // RLEN
    for i in range(n2):
        rec = data[i*RLEN:(i+1)*RLEN]
        if rec[:2] != b'HN':
            continue
        uid = rec[11:21].decode('ascii', errors='replace').strip()
        name_bytes = rec[41:73]
        name = name_bytes.decode(SJIS, errors='replace').replace('　',' ').strip()
        if uid.isdigit() and len(uid) == 10 and name:
            uid_name[uid] = name

print(f"  Total UIDs with names: {len(uid_name)}")
print(f"  Sample:")
for uid, name in list(uid_name.items())[:10]:
    print(f"    {uid} → {name}")

# Now resolve known pedigree IDs
print("\n=== Pedigree resolution for horse 2020100001 ===")
# From earlier: father=1120002295, mother=1220066273
for pid, role in [('1120002295','父'), ('1220066273','母'),
                  ('1120002006','父父'), ('1220046416','父母'),
                  ('1140004605','母父'), ('1240027147','母母')]:
    name = uid_name.get(pid, '(not found)')
    print(f"  {role}: uid={pid} → {name}")
