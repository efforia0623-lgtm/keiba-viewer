"""Search for pedigree data: check SK numeric section + BT text files."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
TFJV = Path(r'C:\TFJV')

# ── 1. SK record pedigree section (bytes 66-205) ──────────────────────
print("=" * 65)
print("1. UM_DATA SK record — 後半バイト (pedigree section?)")
print("=" * 65)

sk = (TFJV / 'UM_DATA/2020/SK220201.DAT').read_bytes()
rlen = 208

# Show records with blood_reg known to us from horse_results
import sqlite3
conn = sqlite3.connect(r'data\keiba.db')
known = {row[0] for row in conn.execute(
    "SELECT blood_reg_num FROM horse_results WHERE SUBSTR(blood_reg_num,1,4)='2020' LIMIT 20"
)}
conn.close()

# For each SK record that matches a known blood_reg, show the pedigree section
n = len(sk) // rlen
print(f"SK records: {n}, known in DB from 2020: {len(known)}")
matches = 0
for i in range(n):
    raw = sk[i*rlen:(i+1)*rlen]
    if raw[:2] != b'SK': continue
    blood = raw[11:21].decode('ascii', errors='?')
    if blood not in known: continue
    matches += 1

    # Decode pedigree section (bytes 66-205 = 140 bytes)
    ped_raw = raw[66:206].decode('ascii', errors='?')
    print(f"\n  blood={blood}")
    print(f"  pedigree bytes[66:206] = {repr(ped_raw[:100])}")

    # Try to parse as 10-digit blood_reg sequences
    ids = []
    for j in range(0, len(ped_raw), 10):
        chunk = ped_raw[j:j+10]
        if chunk.isdigit():
            ids.append(chunk)
    print(f"  10-digit IDs: {ids}")
    if matches >= 3: break

# ── 2. KT_DATA/BT text files ─────────────────────────────────────────
print("\n" + "=" * 65)
print("2. KT_DATA/BT ディレクトリ")
print("=" * 65)
bt_dir = TFJV / 'KT_DATA/BT'
if bt_dir.exists():
    txt_files = sorted(bt_dir.glob('*.TXT'))
    print(f"  .TXT files: {len(txt_files)}")
    # sample first file
    if txt_files:
        sample = txt_files[len(txt_files)//2]
        content = sample.read_bytes()[:600]
        try:
            txt = content.decode(SJIS, errors='replace')
        except:
            txt = content.decode('ascii', errors='replace')
        print(f"  Sample: {sample.name} ({sample.stat().st_size:,} bytes)")
        print(f"  Content: {repr(txt[:200])}")

# ── 3. SaleList.DAT (root-level pedigree?) ───────────────────────────
print("\n" + "=" * 65)
print("3. SaleList.DAT & remaining directories")
print("=" * 65)
sale = TFJV / 'BS_DATA/SaleList.DAT'
if sale.exists():
    d = sale.read_bytes()
    print(f"  SaleList.DAT: {len(d):,} bytes")
    try:
        print(f"  Content: {repr(d[:200].decode(SJIS, errors='replace'))}")
    except: pass

# Check other TFJV directories not yet examined
for dname in ['OW_DATA', 'DE_DATA', 'JG_DATA', 'MY_DATA', 'CS_DATA', 'EX_DATA', 'ES_DATA']:
    d = TFJV / dname
    if not d.exists():
        continue
    entries = list(d.iterdir())
    dats = [e for e in entries if e.is_file() and e.suffix == '.DAT']
    if not dats:
        # subdirs
        subdirs = [e for e in entries if e.is_dir()]
        all_dats = []
        for sd in subdirs[:3]:
            all_dats += list(sd.glob('*.DAT'))
        dats = all_dats[:3]

    if dats:
        f = dats[0]
        data = f.read_bytes()
        prefix = data[:3].decode('ascii', errors='replace')
        print(f"\n  {dname}: {f.name} prefix='{prefix}' size={len(data):,}")
        try:
            print(f"    R1: {repr(data[:150].decode(SJIS, errors='replace'))}")
        except:
            pass
    else:
        print(f"  {dname}: no DAT files found")

# ── 4. KETTO check in UM_DATA SK old files (for named horses) ─────────
print("\n" + "=" * 65)
print("4. SK record - look for father/mother names by cross-referencing")
print("=" * 65)
# Take a well-known horse's blood_reg and check pedigree
# We know from horse_results: blood_reg is 10 digits
# The pedigree section at bytes 66-205 has 140 bytes
# Let's see if any contain recognizable names or matching blood_regs

# Get blood_regs from DB that we also have in UM_DATA
conn2 = sqlite3.connect(r'data\keiba.db')
known_blood = set(row[0] for row in conn2.execute(
    "SELECT DISTINCT blood_reg_num FROM horses WHERE SUBSTR(blood_reg_num,1,4)='2020' LIMIT 50"
))
conn2.close()

# build a lookup: blood_reg → pedigree raw from SK
ped_lookup = {}
for yr in ['2020', '2021', '2022']:
    sk_path = TFJV / f'UM_DATA/{yr}'
    if not sk_path.exists():
        continue
    for f in sk_path.glob('SK*.DAT'):
        data = f.read_bytes()
        n = len(data) // rlen
        for i in range(n):
            raw = data[i*rlen:(i+1)*rlen]
            if raw[:2] != b'SK':
                continue
            blood = raw[11:21].decode('ascii', errors='replace').strip()
            ped_lookup[blood] = raw[66:206]

print(f"  SK pedigree sections loaded: {len(ped_lookup)} horses")

# Show first 3
for blood, ped_bytes in list(ped_lookup.items())[:3]:
    ped_txt = ped_bytes.decode('ascii', errors='replace')
    print(f"\n  blood_reg: {blood}")
    print(f"  raw[66:136]: {repr(ped_txt[:70])}")
    # try 10-digit splits
    ids_10 = [ped_txt[j:j+10] for j in range(0, 130, 10) if ped_txt[j:j+10].isdigit()]
    print(f"  10-digit IDs: {ids_10[:8]}")
