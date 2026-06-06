"""
Pedigree (血統) parser for TARGET frontier JV.

Uses two data sources:
  1. KT_DATA/KT2_XX.DAT  — horse master with UID, names, parent UIDs
  2. UM_DATA/YYYY/SK*.DAT — per-horse pedigree (14 ancestor UIDs)

KT2_XX.DAT record layout (251 bytes, prefix "HN1"):
   0-  2  "HN1"           record type
   3- 10  date            YYYYMMDD (as-of date)
  11- 20  uid             10-digit internal horse ID
  21- 39  numeric_data    19 bytes (sex, year, other codes)
  40- 71  name_sjis       32 bytes Shift-JIS (Japanese name)
  72-103  name_kana       32 bytes half-width katakana reading
 104-167  english_name    64 bytes ASCII
 168-228  other_data      61 bytes (birth info, country, color)
 229-238  father_uid      10-digit internal ID of sire
 239-248  mother_uid      10-digit internal ID of dam
 249-250  CRLF

SK*.DAT pedigree section (bytes 66-205, 140 bytes = 14 × 10-digit UIDs):
  IDs 0-1:  father, mother
  IDs 2-3:  paternal grandfather, paternal grandmother
  IDs 4-5:  maternal grandfather, maternal grandmother
  IDs 6-13: great-grandparents (8 in total)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SJIS = "shift_jis"

# ── KT2 horse master ──────────────────────────────────────────────────
KT2_RLEN  = 251
KT_DATA   = Path(r"C:\TFJV\KT_DATA")
UM_DATA   = Path(r"C:\TFJV\UM_DATA")
SK_RLEN   = 208


def _decode_sjis(raw: bytes) -> str:
    return raw.decode(SJIS, errors="replace").replace("　", " ").strip()


def _decode_ascii(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace").strip()


@dataclass
class HorseNode:
    uid         : str
    name_jp     : str   # 日本語名
    name_en     : str   # English name
    father_uid  : str
    mother_uid  : str


def build_uid_name_map(kt_root: Path = KT_DATA) -> dict[str, HorseNode]:
    """Parse all KT2_XX.DAT files and return uid -> HorseNode mapping."""
    uid_map: dict[str, HorseNode] = {}
    for f in sorted(kt_root.glob("KT2_*.DAT")):
        data = f.read_bytes()
        n = len(data) // KT2_RLEN
        for i in range(n):
            raw = data[i * KT2_RLEN:(i + 1) * KT2_RLEN]
            if raw[:2] != b"HN":
                continue
            uid = _decode_ascii(raw[11:21])
            if not uid.isdigit() or len(uid) != 10:
                continue
            name_jp  = _decode_sjis(raw[40:72])
            name_en  = _decode_ascii(raw[104:168])
            father   = _decode_ascii(raw[229:239])
            mother   = _decode_ascii(raw[239:249])
            uid_map[uid] = HorseNode(
                uid        = uid,
                name_jp    = name_jp,
                name_en    = name_en,
                father_uid = father if father.isdigit() else "",
                mother_uid = mother if mother.isdigit() else "",
            )
    return uid_map


@dataclass
class HorsePedigree:
    blood_reg_num : str

    # Level 1 — parents
    father_uid    : str
    father_name   : str
    mother_uid    : str
    mother_name   : str

    # Level 2 — grandparents
    pat_gf_uid    : str   # paternal grandfather (父父)
    pat_gf_name   : str
    pat_gm_uid    : str   # paternal grandmother (父母)
    pat_gm_name   : str
    mat_gf_uid    : str   # maternal grandfather (母父)
    mat_gf_name   : str
    mat_gm_uid    : str   # maternal grandmother (母母)
    mat_gm_name   : str

    # Level 3 — great-grandparents (8)
    ppgf_uid: str; ppgf_name: str  # 父父父
    ppgm_uid: str; ppgm_name: str  # 父父母
    pmgf_uid: str; pmgf_name: str  # 父母父
    pmgm_uid: str; pmgm_name: str  # 父母母
    mpgf_uid: str; mpgf_name: str  # 母父父
    mpgm_uid: str; mpgm_name: str  # 母父母
    mmgf_uid: str; mmgf_name: str  # 母母父
    mmgm_uid: str; mmgm_name: str  # 母母母


def _resolve(uid: str, uid_map: dict) -> tuple[str, str]:
    """Return (uid, best_name) for a given uid."""
    if not uid or not uid.isdigit():
        return uid, ""
    node = uid_map.get(uid)
    if node is None:
        return uid, ""
    name = node.name_jp if node.name_jp else node.name_en
    return uid, name


def parse_sk_pedigree(raw: bytes, uid_map: dict) -> Optional[HorsePedigree]:
    """Parse one 208-byte SK record and return HorsePedigree."""
    if raw[:2] != b"SK":
        return None
    blood = _decode_ascii(raw[11:21])
    if not blood.isdigit():
        return None

    # Extract 14 ancestor UIDs from bytes 66-205 (14 × 10-byte ASCII)
    ped = raw[66:206].decode("ascii", errors="replace")
    uids = [ped[i:i+10].strip() for i in range(0, 140, 10)]
    uids += [""] * (14 - len(uids))   # pad if short

    def rv(idx): return _resolve(uids[idx] if idx < len(uids) else "", uid_map)

    f_uid,  f_name  = rv(0)
    m_uid,  m_name  = rv(1)
    pgf_uid,pgf_name= rv(2)   # pat.gf  (父父)
    pgm_uid,pgm_name= rv(3)   # pat.gm  (父母)
    mgf_uid,mgf_name= rv(4)   # mat.gf  (母父)
    mgm_uid,mgm_name= rv(5)   # mat.gm  (母母)

    ppgf_uid,ppgf_name = rv(6)
    ppgm_uid,ppgm_name = rv(7)
    pmgf_uid,pmgf_name = rv(8)
    pmgm_uid,pmgm_name = rv(9)
    mpgf_uid,mpgf_name = rv(10)
    mpgm_uid,mpgm_name = rv(11)
    mmgf_uid,mmgf_name = rv(12)
    mmgm_uid,mmgm_name = rv(13)

    return HorsePedigree(
        blood_reg_num=blood,
        father_uid=f_uid,   father_name=f_name,
        mother_uid=m_uid,   mother_name=m_name,
        pat_gf_uid=pgf_uid, pat_gf_name=pgf_name,
        pat_gm_uid=pgm_uid, pat_gm_name=pgm_name,
        mat_gf_uid=mgf_uid, mat_gf_name=mgf_name,
        mat_gm_uid=mgm_uid, mat_gm_name=mgm_name,
        ppgf_uid=ppgf_uid, ppgf_name=ppgf_name,
        ppgm_uid=ppgm_uid, ppgm_name=ppgm_name,
        pmgf_uid=pmgf_uid, pmgf_name=pmgf_name,
        pmgm_uid=pmgm_uid, pmgm_name=pmgm_name,
        mpgf_uid=mpgf_uid, mpgf_name=mpgf_name,
        mpgm_uid=mpgm_uid, mpgm_name=mpgm_name,
        mmgf_uid=mmgf_uid, mmgf_name=mmgf_name,
        mmgm_uid=mmgm_uid, mmgm_name=mmgm_name,
    )


def parse_all_pedigrees(uid_map: dict,
                        um_root: Path = UM_DATA) -> list[HorsePedigree]:
    """Parse all SK files and build pedigree records."""
    results = []
    seen = set()
    for yr_dir in sorted(um_root.iterdir()):
        if not yr_dir.is_dir() or not yr_dir.name.isdigit():
            continue
        for f in sorted(yr_dir.glob("SK*.DAT")):
            data = f.read_bytes()
            n = len(data) // SK_RLEN
            for i in range(n):
                raw = data[i * SK_RLEN:(i + 1) * SK_RLEN]
                ped = parse_sk_pedigree(raw, uid_map)
                if ped and ped.blood_reg_num not in seen:
                    seen.add(ped.blood_reg_num)
                    results.append(ped)
    return results


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("Building UID→name map from KT2 files...")
    uid_map = build_uid_name_map()
    print(f"  {len(uid_map):,} horse UIDs loaded")

    print("Parsing SK pedigree sections...")
    pedigrees = parse_all_pedigrees(uid_map)
    print(f"  {len(pedigrees):,} horse pedigrees parsed")

    print("\nSample (first 5):")
    for p in pedigrees[:5]:
        print(f"  血統:{p.blood_reg_num}")
        print(f"    父: {p.father_name}  母: {p.mother_name}")
        print(f"    父父:{p.pat_gf_name}  父母:{p.pat_gm_name}")
        print(f"    母父:{p.mat_gf_name}  母母:{p.mat_gm_name}")
