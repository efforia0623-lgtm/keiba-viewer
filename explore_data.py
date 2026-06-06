"""Explore UM_DATA, HY_DATA, KT_DATA structure."""
import sys, os
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

roots = {
    'UM_DATA': Path(r'C:\TFJV\UM_DATA'),
    'HY_DATA': Path(r'C:\TFJV\HY_DATA'),
    'KT_DATA': Path(r'C:\TFJV\KT_DATA'),
}

for name, root in roots.items():
    print(f"\n{'='*60}")
    print(f"  {name}  ({root})")
    print(f"{'='*60}")
    # Top-level
    entries = sorted(root.iterdir())
    dirs  = [e for e in entries if e.is_dir()]
    files = [e for e in entries if e.is_file()]
    print(f"  Dirs ({len(dirs)}): {[d.name for d in dirs[:6]]} ...")
    print(f"  Files ({len(files)}): {[f.name for f in files[:6]]} ...")

    # Last year dir
    year_dirs = [d for d in dirs if d.name.isdigit()]
    if year_dirs:
        last = sorted(year_dirs)[-1]
        contents = sorted(last.iterdir())
        print(f"\n  Latest year dir: {last}")
        for f in contents[:10]:
            print(f"    {f.name:30s} {f.stat().st_size:>10,} bytes")

print()
print("=== TFJ_KISI.DAT (root) ===")
p = Path(r'C:\TFJV\TFJ_KISI.DAT')
print(f"  Size: {p.stat().st_size:,} bytes")
data = p.read_bytes()
# Find record length by looking for repeating patterns
for rlen in [200, 210, 220, 230, 240, 250, 260, 270, 280]:
    b0 = data[:3]
    if len(data) % rlen == 0:
        # Check if next record starts similarly
        b1 = data[rlen:rlen+3]
        if b0 == b1:
            print(f"  Possible record length: {rlen} (first 3 bytes match)")
            break
# Print first 100 chars as Shift-JIS
try:
    text = data[:300].decode('shift_jis', errors='replace')
    print(f"  First 100 chars: {repr(text[:100])}")
except:
    pass

print()
print("=== Sample HY file (HY1202613.DAT) ===")
p = Path(r'C:\TFJV\HY_DATA\2026\HY1202613.DAT')
if p.exists():
    data = p.read_bytes()
    print(f"  Size: {data:,}" if isinstance(data, int) else f"  Size: {len(data):,} bytes")
    # Record length detection
    for rlen in [144, 120, 108, 96, 84, 72, 60, 48, 36, 24]:
        if len(data) % rlen == 0:
            b0 = data[:3]
            b1 = data[rlen:rlen+3] if len(data) > rlen else b''
            match = "✓" if b0 == b1 else " "
            print(f"  rlen={rlen:>4}: {len(data)//rlen:>4} records {match}")
    try:
        text = data[:400].decode('shift_jis', errors='replace')
        print(f"  First 150 chars: {repr(text[:150])}")
    except:
        pass
else:
    print("  Not found at expected path")
    # Search for it
    for p2 in Path(r'C:\TFJV').rglob('HY1202613.DAT'):
        print(f"  Found at: {p2}")
