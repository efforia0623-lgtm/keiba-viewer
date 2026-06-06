"""Deep analysis of BS_DATA - find pedigree records."""
import sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
BS_ROOT = Path(r'C:\TFJV\BS_DATA')

def find_rlen(data, max_scan=100000):
    prefix = data[:2]
    pos = [i for i in range(0, min(len(data), max_scan)) if data[i:i+2] == prefix]
    if len(pos) < 3:
        return None
    diffs = [pos[i+1]-pos[i] for i in range(min(len(pos)-1, 100))]
    cnt = Counter(diffs)
    top = cnt.most_common(1)
    return top[0][0] if top else None

def show_records(data, rlen, n=3, label=''):
    print(f"  {label}: rlen={rlen}, total_recs={len(data)//rlen}")
    for i in range(min(n, len(data)//rlen)):
        rec = data[i*rlen:(i+1)*rlen]
        txt = rec.decode(SJIS, errors='replace')
        print(f"  R{i+1}: {repr(txt[:140])}")

# ── 2020 ディレクトリの大きいファイルを調べる ──────────────────────
dir2020 = BS_ROOT / '2020'
files2020 = sorted(dir2020.glob('*.DAT'))
large = [f for f in files2020 if f.stat().st_size > 10000]
small = [f for f in files2020 if f.stat().st_size <= 10000]
print(f"BS_DATA/2020:  大{len(large)}個(>10KB), 小{len(small)}個(<=10KB)")

if large:
    f = large[0]
    data = f.read_bytes()
    print(f"\n=== 大ファイル: {f.name} ({len(data):,} bytes) ===")
    prefix = data[:3]
    print(f"  先頭3バイト: {prefix!r} ({prefix.hex()})")
    rlen = find_rlen(data)
    if rlen:
        show_records(data, rlen, 3, f.name)

    # Hex dump first record
    if rlen:
        rec = data[:rlen]
        print(f"\n  Hex dump ({rlen}bytes):")
        for i in range(0, min(rlen, 160), 16):
            row = rec[i:i+16]
            hex_s = ' '.join(f'{b:02X}' for b in row)
            asc = []
            j = i
            while j < i+16 and j < rlen:
                b = rec[j]
                if b >= 0x81 and j+1 < rlen:
                    try:
                        ch = rec[j:j+2].decode(SJIS, errors='strict')
                        asc.append(ch)
                        j += 2
                        continue
                    except:
                        pass
                asc.append(chr(b) if 32<=b<127 else '·')
                j += 1
            print(f"    {i:03d}: {hex_s:<48}  {''.join(asc)}")

# ── 各年ディレクトリの先頭バイト分布 ──────────────────────────────
print("\n=== 年別・ファイル種類確認 (各年の先頭ファイル) ===")
for yr_dir in sorted(BS_ROOT.glob('*')):
    if not yr_dir.is_dir():
        continue
    dats = sorted(yr_dir.glob('*.DAT'))
    if not dats:
        continue
    prefixes = set()
    for df in dats[:5]:
        d = df.read_bytes()[:3]
        try:
            prefixes.add(d.decode('ascii', errors='replace'))
        except:
            prefixes.add(d.hex())
    sizes = [df.stat().st_size for df in dats]
    print(f"  {yr_dir.name}: {len(dats)}ファイル  プレフィックス={prefixes}  "
          f"サイズ={min(sizes)}-{max(sizes)}bytes")

# ── BY_DATA も確認する ─────────────────────────────────────────
print("\n=== BY_DATA 構造 ===")
by_root = Path(r'C:\TFJV\BY_DATA')
if by_root.exists():
    by_entries = sorted(by_root.iterdir())
    print(f"  エントリ数: {len(by_entries)}")
    for e in by_entries[:5]:
        sz = e.stat().st_size if e.is_file() else '-'
        print(f"  {e.name}  {sz}")
    # 最初のファイルを調べる
    for e in by_entries:
        if e.is_file() and e.suffix == '.DAT':
            d = e.read_bytes()
            rlen = find_rlen(d)
            print(f"\n  {e.name}: {len(d):,}bytes  rlen={rlen}")
            if rlen:
                rec = d[:rlen]
                try:
                    print(f"  Rec1: {repr(rec.decode(SJIS, errors='replace')[:120])}")
                except:
                    pass
            break
else:
    print("  BY_DATA not found")
