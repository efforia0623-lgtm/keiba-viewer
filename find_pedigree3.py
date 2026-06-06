"""Find horse name lookup for pedigree IDs (11/12-prefix internal IDs)."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
TFJV = Path(r'C:\TFJV')

def probe(path, n_bytes=300):
    d = path.read_bytes()[:n_bytes]
    try: return d.decode(SJIS, errors='replace')
    except: return repr(d)

def find_rlen(data, max_scan=30000):
    prefix = data[:2]
    pos = [i for i in range(0, min(len(data), max_scan)) if data[i:i+2] == prefix]
    if len(pos) < 4: return None
    from collections import Counter
    diffs = [pos[i+1]-pos[i] for i in range(min(len(pos)-1,100))]
    top = Counter(diffs).most_common(1)
    return top[0][0] if top else None

# ── STX.DAT at root ──────────────────────────────────────────────────
print("=== STX.DAT (root) ===")
stx = TFJV / 'STX.DAT'
if stx.exists():
    d = stx.read_bytes()
    rlen = find_rlen(d)
    print(f"  Size: {len(d):,}  rlen: {rlen}")
    if rlen:
        n = len(d)//rlen
        print(f"  Records: {n}")
        for i in range(min(3, n)):
            rec = d[i*rlen:(i+1)*rlen]
            print(f"  R{i+1}: {repr(rec.decode(SJIS, errors='replace')[:140])}")

# ── TFJV.CNT ─────────────────────────────────────────────────────────
print("\n=== TFJV.CNT ===")
cnt = TFJV / 'TFJV.CNT'
if cnt.exists():
    d = cnt.read_bytes()
    rlen = find_rlen(d)
    print(f"  Size: {len(d):,}  rlen: {rlen}")
    try: print(f"  First 200: {repr(d[:200].decode(SJIS, errors='replace'))}")
    except: pass

# ── TFJ_*.DAT files anywhere ────────────────────────────────────────
print("\n=== TFJ_*.DAT files in TFJV ===")
for f in sorted(TFJV.rglob('TFJ_*.DAT')):
    d = f.read_bytes()
    rlen = find_rlen(d)
    prefix = d[:3].decode('ascii', errors='replace')
    print(f"  {f.relative_to(TFJV)}: {len(d):,} bytes  prefix={prefix!r}  rlen={rlen}")

# ── Search for pedigree ID "1120002295" in any TFJV file ─────────────
print("\n=== 血統ID 'UM' or 'BT' 馬名ルックアップ ===")
target = b'1120002295'
for f in TFJV.rglob('*.DAT'):
    try:
        d = f.read_bytes()
        if target in d:
            idx = d.index(target)
            ctx = d[max(0,idx-30):idx+80]
            try:
                ctx_str = ctx.decode(SJIS, errors='replace')
            except:
                ctx_str = ctx.hex()
            print(f"  Found in {f.relative_to(TFJV)}: ...{repr(ctx_str)}...")
            break
    except: pass

# ── JG_DATA: collect horse names by blood_reg ───────────────────────
print("\n=== JG_DATA: blood_reg → horse name lookup ===")
jg_root = TFJV / 'JG_DATA'
name_map = {}
if jg_root.exists():
    for f in sorted(jg_root.rglob('*.DAT'))[:50]:  # sample 50 files
        try:
            d = f.read_bytes()
            rlen = find_rlen(d)
            if not rlen: continue
            for i in range(len(d)//rlen):
                rec = d[i*rlen:(i+1)*rlen]
                if rec[:2] != b'JG': continue
                blood = rec[27:37].decode('ascii', errors='replace').strip()
                name_bytes = rec[37:73]
                name = name_bytes.decode(SJIS, errors='replace').replace('　',' ').strip()
                if blood.isdigit() and len(blood)==10 and name:
                    name_map[blood] = name
        except: pass
    print(f"  Collected {len(name_map)} horse names from JG_DATA")
    # Sample
    for blood, name in list(name_map.items())[:10]:
        print(f"    {blood}: {name}")

# ── TFJ KETTO file: OW_DATA for internal structure ───────────────────
print("\n=== OW_DATA full layout ===")
ow_root = TFJV / 'OW_DATA'
if ow_root.exists():
    dats = list(ow_root.glob('*.DAT'))
    if dats:
        d = dats[0].read_bytes()
        rlen = find_rlen(d)
        print(f"  {dats[0].name}: {len(d):,} bytes  rlen={rlen}")
        if rlen:
            rec = d[:rlen]
            print(f"  Rec1 hex:")
            for i in range(0, min(rlen, 120), 16):
                row = rec[i:i+16]
                hex_s = ' '.join(f'{b:02X}' for b in row)
                asc = ''.join(chr(b) if 32<=b<127 else '·' for b in row)
                print(f"    {i:03d}: {hex_s:<48}  {asc}")
