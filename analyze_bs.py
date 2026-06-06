"""Analyze BS_DATA structure and binary format."""
import sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
BS_ROOT = Path(r'C:\TFJV\BS_DATA')

# ── ディレクトリ構造 ──────────────────────────────────────────────
print("=== BS_DATA 全体構造 ===")
year_dirs = sorted([d for d in BS_ROOT.iterdir() if d.is_dir() and d.name.isdigit()])
files_root = [f for f in BS_ROOT.iterdir() if f.is_file()]
print(f"  年ディレクトリ: {year_dirs[0].name}〜{year_dirs[-1].name} ({len(year_dirs)}個)")
print(f"  ルートファイル: {[f.name for f in files_root]}")

# 最新の年ディレクトリ (2025) を詳しく見る
latest = year_dirs[-1]
files_latest = sorted(latest.glob("*.DAT"))
print(f"\n  {latest.name}/")
for f in files_latest[:20]:
    print(f"    {f.name:20s} {f.stat().st_size:>8,} bytes")
if len(files_latest) > 20:
    print(f"    ... 他 {len(files_latest)-20} ファイル")

# ファイル名パターン分析
prefixes = Counter(f.name[:4] for f in files_latest)
print(f"\n  ファイル名プレフィックス: {dict(prefixes)}")

# ── バイナリ解析 ─────────────────────────────────────────────────
# まず大きいファイル (BS2025X.DAT) を解析
big_file = None
for f in files_latest:
    if f.stat().st_size > 10000:
        big_file = f
        break

if big_file:
    print(f"\n=== 大きいファイル: {big_file.name} ({big_file.stat().st_size:,} bytes) ===")
    data = big_file.read_bytes()

    # レコード長検出
    prefix = data[:2]
    positions = [i for i in range(0, min(len(data), 50000))
                 if data[i:i+2] == prefix]
    diffs = sorted(set(positions[i+1]-positions[i] for i in range(min(len(positions)-1, 50))))
    print(f"  先頭2バイト: {prefix!r} ({prefix.hex()})")
    print(f"  同じ先頭バイトの間隔 (diffs): {diffs[:10]}")

    # よく使われるdiffがレコード長
    from collections import Counter
    all_diffs = [positions[i+1]-positions[i] for i in range(min(len(positions)-1, 200))]
    rlen_cand = Counter(all_diffs).most_common(3)
    print(f"  レコード長候補: {rlen_cand}")

    rlen = rlen_cand[0][0] if rlen_cand else None
    if rlen:
        n = len(data) // rlen
        print(f"  確定レコード長: {rlen}  総レコード数: {n:,}")

        # 最初の3レコードを詳しく表示
        print(f"\n  最初の3レコード ({rlen}bytes each):")
        for i in range(min(3, n)):
            rec = data[i*rlen:(i+1)*rlen]
            try:
                txt = rec.decode(SJIS, errors='replace')
            except:
                txt = rec.decode('ascii', errors='replace')
            print(f"  Rec{i+1}: {repr(txt[:120])}")

        # Hex dump of record 1
        print(f"\n  レコード1 hexdump:")
        rec = data[:rlen]
        for i in range(0, min(rlen, 240), 16):
            row = rec[i:i+16]
            hex_s = ' '.join(f'{b:02X}' for b in row)
            # decode as ascii where possible, sjis where needed
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
                asc.append(chr(b) if 32 <= b < 127 else '·')
                j += 1
            print(f"    {i:03d}: {hex_s:<48}  {''.join(asc)}")

# ── 小さいファイルも確認 ──────────────────────────────────────────
small_file = None
for f in files_latest:
    if f.stat().st_size < 10000:
        small_file = f
        break

if small_file:
    print(f"\n=== 小さいファイル: {small_file.name} ({small_file.stat().st_size:,} bytes) ===")
    data2 = small_file.read_bytes()
    prefix2 = data2[:2]
    print(f"  先頭2バイト: {prefix2!r}")
    try:
        print(f"  最初の3行: {repr(data2[:200])}")
    except:
        pass

    # 同じ構造か確認
    if prefix2 == prefix:
        print("  → 同じプレフィックス (同一フォーマット)")
        if rlen:
            n2 = len(data2) // rlen
            print(f"  レコード数: {n2}")
            rec2 = data2[:rlen]
            try:
                print(f"  Rec1: {repr(rec2.decode(SJIS, errors='replace')[:120])}")
            except:
                pass
    else:
        print(f"  → 異なるプレフィックス: {prefix2.hex()}")
