"""Find the actual pedigree (父馬・母馬) data in TFJV."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

SJIS = 'shift_jis'
TFJV = Path(r'C:\TFJV')

def probe(path, max_bytes=400):
    """Read first bytes and decode."""
    try:
        d = path.read_bytes()[:max_bytes]
        return d.decode(SJIS, errors='replace')
    except:
        return ''

def find_rlen(data, max_scan=50000):
    prefix = data[:2]
    pos = [i for i in range(0, min(len(data), max_scan)) if data[i:i+2] == prefix]
    if len(pos) < 4:
        return None
    from collections import Counter
    diffs = [pos[i+1]-pos[i] for i in range(min(len(pos)-1, 100))]
    top = Counter(diffs).most_common(1)
    return top[0][0] if top else None

# 候補ディレクトリを全て確認
candidates = ['BR_DATA', 'BY_DATA', 'BT_DATA', 'TM_DATA', 'RDATA', 'RT_DATA']
print("=== 血統系候補ディレクトリの先頭ファイル解析 ===\n")

for cname in candidates:
    cdir = TFJV / cname
    if not cdir.exists():
        print(f"{cname}: (存在しない)\n")
        continue

    # 年ディレクトリの最新を探す
    dat_files = list(cdir.glob('**/*.DAT'))
    if not dat_files:
        print(f"{cname}: DATファイルなし")
        entries = list(cdir.iterdir())[:3]
        print(f"  内容: {[e.name for e in entries]}\n")
        continue

    # サイズでソートして中くらいのファイルを選ぶ
    dat_files_sorted = sorted(dat_files, key=lambda f: f.stat().st_size)
    sample = dat_files_sorted[len(dat_files_sorted)//2]  # 中間サイズ

    data = sample.read_bytes()
    rlen = find_rlen(data)
    prefix = data[:3].decode('ascii', errors='replace')

    print(f"{cname}/  ({len(dat_files)}個のDAT)  サンプル:{sample.name} ({len(data):,}bytes)")
    print(f"  プレフィックス: '{prefix}'  レコード長: {rlen}")

    if rlen:
        for i in range(min(2, len(data)//rlen)):
            rec = data[i*rlen:(i+1)*rlen]
            txt = rec.decode(SJIS, errors='replace').replace('\r','').replace('\n','')
            print(f"  R{i+1}: {repr(txt[:130])}")
    print()

# TFJ_CHOK.DAT も確認
print("=== TFJ_CHOK.DAT (trainer/調教師?) ===")
chok = TFJV / 'TFJ_CHOK.DAT'
if chok.exists():
    d = chok.read_bytes()
    rlen = find_rlen(d)
    print(f"  {len(d):,}bytes  rlen={rlen}")
    if rlen:
        rec = d[:rlen]
        print(f"  R1: {repr(rec.decode(SJIS,errors='replace')[:120])}")

# CHECKKETTO.LST を確認 (血統リスト?)
print("\n=== CHECKKETTO.LST ===")
ketto = TFJV / 'CHECKKETTO.LST'
if ketto.exists():
    d = ketto.read_bytes()
    print(f"  {len(d):,}bytes")
    print(f"  内容(先頭): {repr(d[:200])}")
