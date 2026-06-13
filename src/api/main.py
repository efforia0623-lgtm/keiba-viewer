"""競馬AI予想 FastAPI バックエンド"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from src.parser.finish_margin import decode_finish_margin as _decode_finish_margin

ROOT    = Path(__file__).parents[2]
DB_PATH = ROOT / "data" / "keiba.db"

# analyze_keshi を import（project root 配下にある）
import sys as _sys
_sys.path.insert(0, str(ROOT))
from analyze_keshi import (
    find_past_races    as _keshi_find_races,
    collect_horse_data as _keshi_collect_horses,
    compute_keshi      as _keshi_compute,
)

VENUE_NAMES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
    "30": "門別", "35": "盛岡", "36": "水沢",
    "42": "浦和", "43": "船橋", "44": "大井",  "45": "川崎",
    "46": "金沢", "47": "笠松", "48": "名古屋",
    "50": "園田", "51": "姫路", "54": "高知",  "55": "佐賀",
    "65": "帯広",
}

TRACK_MAP = {"芝": 1, "ダート": 2, "障害": 3}
SEX_MAP   = {"10": 1, "20": 2, "30": 3, "40": 4,
             "1":  1, "2":  2, "3":  3}

# NAR会場のデフォルトコース種別（condition_textがNULLの場合に使用）
_NAR_TRACK: dict[str, str] = {
    "30": "ダート", "36": "ダート", "42": "ダート", "43": "ダート",
    "44": "ダート", "45": "ダート", "46": "ダート", "47": "ダート",
    "48": "ダート", "50": "ダート", "51": "ダート", "54": "ダート",
    "55": "ダート", "65": "障害",
}

# ── ⑤照合スコア用: 消し条件関数 (module-level; analyze_keshi と同じキー名を使用) ──

def _kc_finish_ge5(h):   return h.get("prev_finish_pos") is not None and h["prev_finish_pos"] >= 5
def _kc_finish_ge8(h):   return h.get("prev_finish_pos") is not None and h["prev_finish_pos"] >= 8
def _kc_pop_ge4(h):      return h.get("prev_popularity") is not None and h["prev_popularity"] >= 4
def _kc_pop_ge7(h):      return h.get("prev_popularity") is not None and h["prev_popularity"] >= 7
def _kc_margin_ge15(h):  return h.get("prev_margin") is not None and h["prev_margin"] >= 1.5
def _kc_margin_ge30(h):  return h.get("prev_margin") is not None and h["prev_margin"] >= 3.0
def _kc_dart_to_turf(h): return h.get("prev_track_type") == "ダート" and h.get("target_track_type") == "芝"
def _kc_turf_to_dart(h): return h.get("prev_track_type") == "芝"    and h.get("target_track_type") == "ダート"
def _kc_shorten_200(h):
    pd, td = h.get("prev_distance"), h.get("target_distance")
    return pd is not None and td is not None and (pd - td) >= 200
def _kc_extend_400(h):
    pd, td = h.get("prev_distance"), h.get("target_distance")
    return pd is not None and td is not None and (td - pd) >= 400
def _kc_interval_90(h):  return h.get("prev_days") is not None and h["prev_days"] >= 90
def _kc_interval_14(h):  return h.get("prev_days") is not None and 0 < h["prev_days"] <= 14
def _kc_age_ge8(h):      return h.get("horse_age") is not None and h["horse_age"] >= 8
def _kc_career_le5(h):   return (h.get("career") or 0) <= 5
def _kc_grade_not_g1(h): return h.get("prev_grade_code", "") in ("B","C","2","3")
def _kc_grade_g2(h):     return h.get("prev_grade_code", "") in ("B","2")
def _kc_grade_tokubetsu(h):
    gc = h.get("prev_grade_code", "") or ""
    return gc != "" and gc not in ("A","B","C","D","E","F","1","2","3")
def _kc_joken(h):
    return not (h.get("prev_race_name") or "") and not (h.get("prev_grade_code") or "")

_KESHI_CONDITIONS: list[tuple] = [
    ("前走5着以下",         _kc_finish_ge5),
    ("前走8着以下",         _kc_finish_ge8),
    ("前走4番人気以下",     _kc_pop_ge4),
    ("前走7番人気以下",     _kc_pop_ge7),
    ("前走1.5馬身以上負け", _kc_margin_ge15),
    ("前走3馬身以上負け",   _kc_margin_ge30),
    ("前走ダート→今回芝",  _kc_dart_to_turf),
    ("前走芝→今回ダート",  _kc_turf_to_dart),
    ("前走200m以上短縮",   _kc_shorten_200),
    ("前走400m以上延長",   _kc_extend_400),
    ("前走90日以上間隔",   _kc_interval_90),
    ("前走14日以内",       _kc_interval_14),
    ("8歳以上",            _kc_age_ge8),
    ("キャリア5戦以内",    _kc_career_le5),
    ("前走G1以外の重賞",   _kc_grade_not_g1),
    ("前走G2",             _kc_grade_g2),
    ("前走特別戦以下",     _kc_grade_tokubetsu),
    ("前走条件競走",       _kc_joken),
]


@lru_cache(maxsize=256)
def _get_track_type_cached(venue: str, distance_bucket: int) -> str:
    """JRA会場の距離バケット(100m単位)ごとのtrack_typeをキャッシュして返す。"""
    dist = distance_bucket * 100
    with _db() as db:
        try:
            row = db.execute("""
                SELECT track_type FROM horse_results
                WHERE venue_code = ? AND distance BETWEEN ? AND ?
                  AND track_type IS NOT NULL
                GROUP BY track_type ORDER BY COUNT(*) DESC LIMIT 1
            """, (venue, dist - 100, dist + 100)).fetchone()
            return row[0] if row else ""
        except Exception:
            return ""


def _get_track_type(venue: str, distance, db=None) -> str:
    """会場コードと距離からコース種別を推定する（JRA会場はキャッシュ利用）。"""
    if venue == "35":  # 盛岡：芝(~1200m) / ダート
        try:
            return "芝" if int(distance or 0) <= 1200 else "ダート"
        except (TypeError, ValueError):
            return "ダート"
    if venue in _NAR_TRACK:
        return _NAR_TRACK[venue]
    # JRA会場：lru_cacheで高速化（同一会場距離は結果が変わらない）
    if distance:
        try:
            bucket = round(int(distance) / 100)
            return _get_track_type_cached(venue, bucket)
        except (TypeError, ValueError):
            pass
    return ""

# model_placed_pure.lgb の特徴量（popularity なし・41列）
FEATURES = [
    "distance", "track_type_enc", "venue_int",
    "horse_pos_1", "horse_pos_2", "horse_pos_3", "horse_pos_4", "horse_pos_5",
    "horse_agari_1", "horse_agari_2", "horse_agari_3", "horse_agari_4", "horse_agari_5",
    "horse_avg_pos_5", "horse_win_rate_5", "horse_place_rate_5", "horse_avg_agari_5",
    "horse_n_races", "horse_days_last_race", "horse_avg_corner4",
    "horse_venue_avg_pos", "horse_venue_win_rate", "horse_venue_races",
    "gate_num_int", "horse_num_int", "starters",
    "horse_age_int", "sex_enc", "horse_weight", "weight_change_int",
    "jockey_win30", "jockey_place30", "jockey_rides30", "jockey_win60",
    "trainer_win30", "trainer_win60",
    "tr_days_before", "tr_4f_last", "tr_1f_last", "tr_4f_avg14d", "tr_sessions_14d",
]

_model: Optional[lgb.Booster] = None
_prediction_cache: dict[str, bytes] = {}  # key: "date:venue:race" → UTF-8 JSON bytes

# ── 複合スコア: prob × (total_score/60)^COMPOSITE_ALPHA で印を決める ─────────
# α=0: probのみ(モデル依存)  α=1: prob×スコアを対等に掛ける  α>1: スコア支配的
# 本番実績蓄積後に調整すること
COMPOSITE_ALPHA: float = 1.0

# ── ②血統 手動注入 ──────────────────────────────────────────────────────────
_BLOOD_MANUAL_PATH = ROOT / "data" / "blood_manual.json"
_BLOOD_RANK_SCORES: dict[str, float] = {
    "S": 9.0, "A+": 8.0, "A": 7.0, "B+": 6.5, "B": 6.0, "C": 4.0,
}
_blood_manual_cache: dict = {}
_blood_manual_mtime: float = 0.0


def _load_manual_blood() -> dict:
    """blood_manual.jsonをロード(変更があれば自動リロード)。存在しない・壊れた場合は空dict。"""
    global _blood_manual_cache, _blood_manual_mtime
    try:
        mtime = _BLOOD_MANUAL_PATH.stat().st_mtime
        if mtime != _blood_manual_mtime:
            _blood_manual_cache = json.loads(_BLOOD_MANUAL_PATH.read_text(encoding="utf-8"))
            _blood_manual_mtime = mtime
    except FileNotFoundError:
        _blood_manual_cache = {}
    except Exception:
        pass  # 読み込みエラー時はキャッシュをそのまま使用
    return _blood_manual_cache


def _get_manual_s2(date: str, venue: str, race_num: str, horse_num: str) -> Optional[float]:
    """手動血統スコアを返す。入力なし → None(統計②フォールバック)。"""
    ratings = _load_manual_blood()
    race_key = f"{venue}-{race_num}"
    horse_data = ratings.get(date, {}).get(race_key, {}).get("horses", {})
    entry = horse_data.get(str(horse_num))
    if entry is None:
        return None
    rank = entry.get("rank", "") if isinstance(entry, dict) else str(entry)
    return _BLOOD_RANK_SCORES.get(rank)


def _json_bytes(obj) -> bytes:
    """numpy/None 混在 dict を UTF-8 JSON bytes に変換する。"""
    import json

    class _Enc(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.integer,)):  return int(o)
            if isinstance(o, (np.floating,)): return None if not np.isfinite(o) else float(o)
            if isinstance(o, np.ndarray):     return o.tolist()
            return super().default(o)

    return json.dumps(obj, cls=_Enc, ensure_ascii=False).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    p = ROOT / "data" / "model_placed_pure.lgb"
    if p.exists():
        _model = lgb.Booster(model_file=str(p))
        print(f"Model loaded: {_model.num_trees()} trees, {_model.num_feature()} features")
    else:
        print("WARNING: model_placed_pure.lgb not found")
    yield
    _model = None


app = FastAPI(title="競馬AI予想API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── ユーティリティ ─────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _f(v, default: float = np.nan) -> float:
    try:
        r = float(v)
        return r if np.isfinite(r) else default
    except (TypeError, ValueError):
        return default


def _date_sub(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")


def _days_between(d1: str, d2: str) -> float:
    try:
        return float((datetime.strptime(d1, "%Y%m%d") - datetime.strptime(d2, "%Y%m%d")).days)
    except Exception:
        return np.nan


# ── 1. 開催日一覧 ─────────────────────────────────────────────────────────────

@app.get("/api/dates")
def get_dates():
    with _db() as db:
        rows = db.execute("""
            SELECT DISTINCT race_date FROM entries
            ORDER BY race_date DESC LIMIT 30
        """).fetchall()
    return {"dates": [{"date": r[0], "has_entries": True} for r in rows]}


# ── 2. 競馬場一覧 ─────────────────────────────────────────────────────────────

@app.get("/api/venues")
def get_venues(date: str = Query(...)):
    with _db() as db:
        rows = db.execute("""
            SELECT venue_code, meeting_num, day_num
            FROM entries WHERE race_date = ?
            GROUP BY venue_code ORDER BY venue_code
        """, (date,)).fetchall()
    if not rows:
        raise HTTPException(404, "No races found for this date")
    return {"date": date, "venues": [
        {
            "venue_code":  r[0],
            "venue_name":  VENUE_NAMES.get(r[0], r[0]),
            "meeting_num": r[1],
            "day_num":     r[2],
        }
        for r in rows
    ]}


# ── 3. レース一覧 ─────────────────────────────────────────────────────────────

@app.get("/api/races")
def get_races(date: str = Query(...), venue: str = Query(...)):
    with _db() as db:
        rows = db.execute("""
            SELECT race_num,
                   MAX(race_name)  race_name,
                   MAX(distance)   distance,
                   MAX(grade_code) grade_code,
                   MAX(day_num)    day_num,
                   COUNT(*)        starters
            FROM entries WHERE race_date = ? AND venue_code = ?
            GROUP BY race_num ORDER BY CAST(race_num AS INTEGER)
        """, (date, venue)).fetchall()
    if not rows:
        raise HTTPException(404, "No races found")
    with _db() as db2:
        return {"date": date, "venue": venue, "races": [
            {
                "race_num":   r[0],
                "race_name":  (r[1] or "").strip() or f"{r[0]}R",
                "distance":   r[2],
                "grade_code": (r[3] or "").strip(),
                "day_num":    r[4],
                "starters":   r[5],
                "track_type": _get_track_type(venue, r[2], db2),
            }
            for r in rows
        ]}


# ── 4. 出馬表 ─────────────────────────────────────────────────────────────────

@app.get("/api/entries")
def get_entries(
    date:  str = Query(...),
    venue: str = Query(...),
    race:  str = Query(...),
):
    with _db() as db:
        rows = db.execute("""
            SELECT e.horse_num, e.gate_num, e.blood_reg_num,
                   e.horse_name, e.horse_age, e.sex_code,
                   e.jockey_name, e.jockey_code, e.trainer_name,
                   e.body_weight, e.race_name, e.distance,
                   e.grade_code, e.condition_text, e.day_num,
                   COUNT(hr.race_date) past_races
            FROM entries e
            LEFT JOIN horse_results hr ON hr.blood_reg_num = e.blood_reg_num
            WHERE e.race_date=? AND e.venue_code=? AND e.race_num=?
            GROUP BY e.horse_num
            ORDER BY CAST(e.horse_num AS INTEGER)
        """, (date, venue, race)).fetchall()
    if not rows:
        raise HTTPException(404, "No entries found")

    SEX_JP = {"1": "牡", "2": "牝", "3": "騸", "10": "牡", "20": "牝", "30": "騸"}
    r0 = rows[0]
    dist = r0["distance"]
    with _db() as db2:
        tt = _get_track_type(venue, dist, db2)
    return {
        "race_info": {
            "date":       date,
            "venue_code": venue,
            "venue_name": VENUE_NAMES.get(venue, venue),
            "race_num":   race,
            "day_num":    r0["day_num"],
            "race_name":  (r0["race_name"] or f"{race}R").strip(),
            "distance":   dist,
            "grade_code": (r0["grade_code"] or "").strip(),
            "starters":   len(rows),
            "track_type": tt,
        },
        "horses": [
            {
                "horse_num":     r["horse_num"],
                "gate_num":      r["gate_num"] or "",
                "blood_reg_num": r["blood_reg_num"],
                "horse_name":    r["horse_name"] or "",
                "horse_age":     r["horse_age"],
                "sex":           SEX_JP.get(r["sex_code"] or "", ""),
                # DBではjockey_nameとtrainer_nameが逆に格納されているため表示用にスワップ
                "jockey_name":   r["trainer_name"] or "",
                "jockey_code":   r["jockey_code"] or "",
                "trainer_name":  r["jockey_name"] or "",
                "body_weight":   r["body_weight"],
                "past_races":    r["past_races"],
            }
            for r in rows
        ],
    }


# ── 5. 特徴量ビルド ───────────────────────────────────────────────────────────

def _compute_bias(venue: str, track_type: str, distance: float,
                  track_condition: str, date: str) -> dict:
    """④用: 15年・同会場・同コース・段階フォールバックで脚質/枠バイアスを集計。
    段階1(±100m+同馬場) → 段階2(±200m+同馬場) → 段階3(±200m+良系/悪系グループ)
    → 段階4(±200m+馬場問わず) → 段階5(N<50, 空dict)の順で採用。
    + ③用: 15年・±200m・馬場問わずの馬番別複勝率(ベイズk=30)も同時取得。"""
    d15yr   = _date_sub(date, 5475)
    dist_lo = max(0, int(distance) - 200)
    dist_hi = int(distance) + 200

    # 馬場グループ: 良/稍重 系 vs 重/不良 系
    tc_good = ("良", "稍重")
    tc_bad  = ("重", "不良")
    tc_grp  = tc_bad if (track_condition or "") in tc_bad else tc_good

    # ④用フォールバック段階定義 (dist_delta, tc_mode)
    # tc_mode: "exact"=同馬場, "group"=グループ, "any"=問わず
    STAGES = [
        (100, "exact", "1"),
        (200, "exact", "2"),
        (200, "group", "3"),
        (200, "any",   "4"),
    ]

    def _fetch_bias_rows(dist_delta: int, tc_mode: str):
        dl = max(0, int(distance) - dist_delta)
        dh = int(distance) + dist_delta
        with _db() as db:
            if tc_mode == "exact":
                return db.execute("""
                    SELECT race_style, gate_num, finish_pos
                    FROM horse_results
                    WHERE venue_code=? AND track_type=?
                      AND distance BETWEEN ? AND ?
                      AND track_condition=?
                      AND race_date BETWEEN ? AND ?
                      AND finish_pos IS NOT NULL AND finish_pos > 0
                      AND race_style IS NOT NULL AND race_style != ''
                """, (venue, track_type, dl, dh, track_condition, d15yr, date)).fetchall()
            elif tc_mode == "group":
                ph = ",".join("?" * len(tc_grp))
                return db.execute(f"""
                    SELECT race_style, gate_num, finish_pos
                    FROM horse_results
                    WHERE venue_code=? AND track_type=?
                      AND distance BETWEEN ? AND ?
                      AND track_condition IN ({ph})
                      AND race_date BETWEEN ? AND ?
                      AND finish_pos IS NOT NULL AND finish_pos > 0
                      AND race_style IS NOT NULL AND race_style != ''
                """, (venue, track_type, dl, dh, *tc_grp, d15yr, date)).fetchall()
            else:  # "any"
                return db.execute("""
                    SELECT race_style, gate_num, finish_pos
                    FROM horse_results
                    WHERE venue_code=? AND track_type=?
                      AND distance BETWEEN ? AND ?
                      AND race_date BETWEEN ? AND ?
                      AND finish_pos IS NOT NULL AND finish_pos > 0
                      AND race_style IS NOT NULL AND race_style != ''
                """, (venue, track_type, dl, dh, d15yr, date)).fetchall()

    # ③用: 馬番別複勝率 (15年・±200m・馬場問わず) — 段階に関係なく常に取得
    with _db() as db:
        gate_rows = db.execute("""
            SELECT CAST(horse_num AS INTEGER) AS hnum,
                   COUNT(*) AS n,
                   SUM(CASE WHEN finish_pos <= 3 THEN 1 ELSE 0 END) AS placed
            FROM horse_results
            WHERE venue_code=? AND track_type=?
              AND distance BETWEEN ? AND ?
              AND race_date BETWEEN ? AND ?
              AND finish_pos IS NOT NULL AND finish_pos > 0
              AND horse_num IS NOT NULL AND horse_num != ''
            GROUP BY CAST(horse_num AS INTEGER)
        """, (venue, track_type, dist_lo, dist_hi, d15yr, date)).fetchall()

    # ④フォールバック: N>=50 の最初の段階を採用
    rows      = []
    bias_stage = "5"
    for dist_delta, tc_mode, stage_label in STAGES:
        candidate = _fetch_bias_rows(dist_delta, tc_mode)
        if len(candidate) >= 50:
            rows       = candidate
            bias_stage = stage_label
            break

    # ③馬番データ: 段階に関係なく常に計算
    _gn_total = sum(int(r["n"]) for r in gate_rows)
    _gn_prior = (sum(int(r["placed"]) for r in gate_rows) / _gn_total
                 if _gn_total > 0 else 0.33)
    _k = 30
    horse_num_rates: dict[int, float] = {}
    for r in gate_rows:
        try:
            hn = int(r["hnum"])
        except (ValueError, TypeError):
            continue
        n   = int(r["n"])
        raw = int(r["placed"]) / n if n > 0 else _gn_prior
        horse_num_rates[hn] = (n * raw + _k * _gn_prior) / (n + _k)

    if not rows:  # 段階5: ④バイアス集計不能
        return {
            "horse_num_rates": horse_num_rates,
            "horse_num_prior": _gn_prior,
            "bias_stage":      "5",
            "n_total":         0,
        }

    # ④バイアス集計
    total          = len(rows)
    avg_place_rate = sum(1 for r in rows if r["finish_pos"] <= 3) / total
    style_total:  dict[str, int] = defaultdict(int)
    style_placed: dict[str, int] = defaultdict(int)
    gate_total:   dict[str, int] = defaultdict(int)
    gate_placed:  dict[str, int] = defaultdict(int)

    for r in rows:
        s = r["race_style"]
        style_total[s]  += 1
        style_placed[s] += 1 if r["finish_pos"] <= 3 else 0
        try:
            g  = int(r["gate_num"])
            br = "inner" if g <= 4 else ("middle" if g <= 8 else "outer")
        except (ValueError, TypeError):
            br = "middle"
        gate_total[br]  += 1
        gate_placed[br] += 1 if r["finish_pos"] <= 3 else 0

    style_bias = {
        s: (style_placed[s] / style_total[s] - avg_place_rate if style_total[s] > 0 else 0.0)
        for s in "1234"
    }
    gate_bias = {
        br: (gate_placed[br] / gate_total[br] - avg_place_rate if gate_total[br] > 0 else 0.0)
        for br in ("inner", "middle", "outer")
    }

    return {
        "style_bias":      style_bias,
        "gate_bias":       gate_bias,
        "horse_num_rates": horse_num_rates,
        "horse_num_prior": _gn_prior,
        "bias_stage":      bias_stage,
        "n_total":         total,
    }


@lru_cache(maxsize=64)
def _keshi_thresholds(toku_race_num: str, date: str) -> tuple:
    """過去の同名重賞から有効消し条件 (diff_pp≤-6pp, N≥10) をキャッシュして返す。"""
    if not toku_race_num or toku_race_num == "0000":
        return ()
    with _db() as db:
        past_races = _keshi_find_races(toku_race_num, date, db)
    if not past_races:
        return ()
    with _db() as db:
        horse_data = _keshi_collect_horses(past_races, db)
    if not horse_data:
        return ()

    total      = len(horse_data)
    placed_n   = sum(1 for h in horse_data if h["placed"])
    base_rate  = placed_n / total if total else 0.0

    valid: list[tuple] = []
    for label, fn in _KESHI_CONDITIONS:
        stats = _keshi_compute(horse_data, fn, label, base_rate)
        if stats and stats["diff_pp"] <= -6.0 and stats["n"] >= 10:
            valid.append((label, stats["diff_pp"], stats["n"], fn))
    return tuple(valid)


def _horse_keshi_score(keshi_h: dict, thresholds: tuple) -> int:
    """
    有効消し条件を今日の馬に適用してスコアを返す。
    penalty上限4.0 → score = max(2, round(10 - penalty*2))
    thresholds が空（非重賞・データなし）= 5点(中立)。
    """
    if not thresholds:
        return 5
    penalty = 0.0
    for label, diff_pp, n, fn in thresholds:
        try:
            if fn(keshi_h):
                if diff_pp <= -10.0 and n >= 30:
                    w = 2.5
                elif diff_pp <= -10.0:
                    w = 1.5
                elif diff_pp <= -6.0 and n >= 20:
                    w = 1.5
                else:
                    w = 0.8
                penalty += w
        except Exception:
            pass
    penalty = min(penalty, 4.0)
    return max(2, round(10 - penalty * 2))


def _build_sire_stats(rows) -> dict:
    """
    GROUP BY rows (sire_name, track_type, dist_bracket, venue_code, n, places)
    → {sire_name: {track_type: {'base': {'n','places'}, 'dist': {...}, 'venue': {...}}}}
    """
    stats: dict = {}
    for r in rows:
        sn = r["sire_name"] or ""
        tt = r["track_type"] or ""
        db_ = r["dist_bracket"] or ""
        vc = r["venue_code"] or ""
        n  = int(r["n"]      or 0)
        pl = int(r["places"] or 0)
        if not sn or not tt:
            continue
        if sn not in stats:
            stats[sn] = {}
        if tt not in stats[sn]:
            stats[sn][tt] = {"base": {"n": 0, "places": 0}, "dist": {}, "venue": {}}
        s = stats[sn][tt]
        s["base"]["n"]      += n
        s["base"]["places"] += pl
        if db_:
            d = s["dist"].setdefault(db_, {"n": 0, "places": 0})
            d["n"]      += n
            d["places"] += pl
        if vc:
            v = s["venue"].setdefault(vc, {"n": 0, "places": 0})
            v["n"]      += n
            v["places"] += pl
    return stats


def _sire_ratios(sire_name: str, track_type: str, dist_bracket: str,
                 venue: str, stats: dict) -> tuple[float, float]:
    """
    Returns (dist_ratio, venue_ratio): sire's Bayesian-adjusted place rate for the
    specific condition divided by sire's baseline for the same track_type.
    ratio > 1.0 = better than sire's average; < 1.0 = worse.
    Falls back to (1.0, 1.0) when data is missing.
    """
    _PRIOR_N    = 20
    _PRIOR_RATE = 0.33

    def _adj(n: int, pl: int) -> float:
        return (_PRIOR_RATE * _PRIOR_N + pl) / (_PRIOR_N + n)

    if not sire_name or sire_name not in stats:
        return 1.0, 1.0
    tt_data = stats[sire_name].get(track_type)
    if not tt_data:
        return 1.0, 1.0

    base_rate = _adj(tt_data["base"]["n"], tt_data["base"]["places"])
    if base_rate <= 0:
        return 1.0, 1.0

    dd = tt_data["dist"].get(dist_bracket, {"n": 0, "places": 0})
    vv = tt_data["venue"].get(venue,        {"n": 0, "places": 0})
    return _adj(dd["n"], dd["places"]) / base_rate, _adj(vv["n"], vv["places"]) / base_rate


# 同コース種別グローバル複勝率（実測値・定数）
# 芝22.29% / ダート21.23% (7年・345,260走 実測)
_GLOBAL_TRACK_RATE: dict[str, float] = {"芝": 0.2229, "ダート": 0.2123}
_SIRE_ABS_MIN_N: int = 30  # 絶対評価に最低限必要なサンプル数


def _sire_abs_score(sire_name: str, track_type: str, stats: dict) -> float:
    """
    Returns absolute strength score (1-10) for sire on this track_type.
    Uses raw place rate (not Bayesian) vs global track_type rate.
    Falls back to 5.0 (neutral) when n < _SIRE_ABS_MIN_N or data missing.
    """
    if not sire_name or sire_name not in stats:
        return 5.0
    tt_data = stats[sire_name].get(track_type)
    if not tt_data:
        return 5.0
    base = tt_data["base"]
    n, pl = base["n"], base["places"]
    if n < _SIRE_ABS_MIN_N:
        return 5.0
    raw_rate = pl / n
    global_rate = _GLOBAL_TRACK_RATE.get(track_type, 0.22)
    return float(np.clip(5.0 * raw_rate / global_rate, 1.0, 10.0))


def _build_features(date: str, venue: str, race_num: str,
                    track_condition: Optional[str] = None) -> list[dict]:
    d30  = _date_sub(date, 30)
    d60  = _date_sub(date, 60)
    d14  = _date_sub(date, 14)
    d3yr = _date_sub(date, 1095)  # 調教データの上限（3年、自己比較に使う）
    d5yr = _date_sub(date, 1825)  # 過去成績の上限（5年）

    with _db() as db:
        # ① 出走馬（entriesから）
        entries = db.execute("""
            SELECT horse_num, gate_num, blood_reg_num, horse_name,
                   horse_age, sex_code, body_weight, jockey_code,
                   jockey_name, trainer_name, distance, track_type,
                   race_name, grade_code
            FROM entries
            WHERE race_date=? AND venue_code=? AND race_num=?
            ORDER BY CAST(horse_num AS INTEGER)
        """, (date, venue, race_num)).fetchall()

        if not entries:
            return []

        starters   = len(entries)
        blood_list = [e["blood_reg_num"] for e in entries]
        ph         = ",".join("?" * len(blood_list))

        # 今回のコース種別（entries.track_typeが優先、NULLなら推定）
        _entry_tt = entries[0]["track_type"] if entries[0]["track_type"] else None
        race_track_type = _entry_tt or _get_track_type(venue, entries[0]["distance"])

        # 今回の馬場状態（パラメータ優先、なければDBから取得、デフォルト'良'）
        if not track_condition:
            _tc_row = db.execute("""
                SELECT track_condition FROM horse_results
                WHERE race_date=? AND venue_code=? AND race_num=?
                  AND track_condition IS NOT NULL AND track_condition != ''
                LIMIT 1
            """, (date, venue, race_num)).fetchone()
            track_condition = _tc_row["track_condition"] if _tc_row else "良"

        # ⑨ 今回レースの toku_race_num（レース名ベースで検索）
        # '0000' は「特別競走なし」の JV-Data フィラー値。条件競走は keshi 対象外。
        _grade = (entries[0]["grade_code"] or "").strip() if entries else ""
        _race_name_raw = (entries[0]["race_name"] or "").strip() if entries else ""
        race_toku_num = ""
        if _grade in ("A","B","C","D","1","2","3") and _race_name_raw:
            # race_name の先頭語（空白・全角スペース前）を抽出してLIKE検索
            _rn_clean = _race_name_raw.replace("　", " ")
            _main_name = _rn_clean.split()[0] if _rn_clean.split() else ""
            if _main_name:
                _toku_row = db.execute("""
                    SELECT toku_race_num FROM horse_results
                    WHERE (TRIM(race_name) = ? OR race_name LIKE ?)
                      AND toku_race_num IS NOT NULL
                      AND toku_race_num != '' AND toku_race_num != '0000'
                      AND CAST(toku_race_num AS INTEGER) > 0
                      AND race_date < ?
                    ORDER BY race_date DESC LIMIT 1
                """, (_main_name, "%" + _main_name + "%", date)).fetchone()
                race_toku_num = _toku_row["toku_race_num"] if _toku_row else ""

        # ② 各馬の過去成績（直近5年・ORDER BY を Python ソートに移して高速化）
        history = db.execute(f"""
            SELECT blood_reg_num, race_date, venue_code, race_num,
                   finish_pos, agari_3f, corner4, track_type,
                   distance, finish_margin, race_style,
                   popularity, grade_code, race_name, dist_class
            FROM horse_results
            WHERE blood_reg_num IN ({ph})
              AND race_date BETWEEN ? AND ?
              AND finish_pos IS NOT NULL
        """, blood_list + [d5yr, date]).fetchall()

        # ③ 騎手成績（過去60日）
        # idx_hr_jockey_date（複合インデックス）で高速化
        jcodes = list({e["jockey_code"] for e in entries if e["jockey_code"]})
        if jcodes:
            jph = ",".join("?" * len(jcodes))
            j_rows = db.execute(f"""
                SELECT jockey_code,
                       SUM(CASE WHEN race_date >= ? THEN 1 ELSE 0 END)                  rides30,
                       SUM(CASE WHEN race_date >= ? AND finish_pos=1 THEN 1 ELSE 0 END) wins30,
                       SUM(CASE WHEN race_date >= ? AND finish_pos<=3 THEN 1 ELSE 0 END) places30,
                       COUNT(*)                                                           rides60,
                       SUM(CASE WHEN finish_pos=1 THEN 1 ELSE 0 END)                    wins60
                FROM horse_results
                WHERE jockey_code IN ({jph})
                  AND race_date BETWEEN ? AND ?
                  AND finish_pos IS NOT NULL
                GROUP BY jockey_code
            """, [d30, d30, d30] + jcodes + [d60, date]).fetchall()
        else:
            j_rows = []

        # ④ 調教師成績（過去60日）
        # idx_hr_trainer_date（複合インデックス）で高速化
        tnames = list({e["trainer_name"] for e in entries if e["trainer_name"]})
        if tnames:
            tph = ",".join("?" * len(tnames))
            t_rows = db.execute(f"""
                SELECT trainer_name,
                       SUM(CASE WHEN race_date >= ? THEN 1 ELSE 0 END)                  rides30,
                       SUM(CASE WHEN race_date >= ? AND finish_pos=1 THEN 1 ELSE 0 END) wins30,
                       COUNT(*)                                                           rides60,
                       SUM(CASE WHEN finish_pos=1 THEN 1 ELSE 0 END)                    wins60
                FROM horse_results
                WHERE trainer_name IN ({tph})
                  AND race_date BETWEEN ? AND ?
                  AND finish_pos IS NOT NULL
                GROUP BY trainer_name
            """, [d30, d30] + tnames + [d60, date]).fetchall()
        else:
            t_rows = []

        # ⑥ 調教データ（直近3年：自己比較に使う）
        tr_rows = db.execute(f"""
            SELECT blood_reg_num, training_date, venue_code,
                   time_4f, time_1f_last, extra_raw
            FROM training
            WHERE blood_reg_num IN ({ph})
              AND training_date >= ?
              AND time_4f IS NOT NULL AND time_4f > 0
            ORDER BY blood_reg_num, training_date DESC
        """, blood_list + [d3yr]).fetchall()

        # ⑦ 馬場適性: 今回コース種別・今回馬場状態での各馬成績（一括取得）
        tc_rows_q = db.execute(f"""
            SELECT blood_reg_num,
                   SUM(CASE WHEN track_condition=? AND finish_pos > 0 THEN 1 ELSE 0 END) tc_n,
                   SUM(CASE WHEN track_condition=? AND finish_pos <= 3 THEN 1 ELSE 0 END) tc_placed
            FROM horse_results
            WHERE track_type=?
              AND race_date < ?
              AND blood_reg_num IN ({ph})
              AND finish_pos IS NOT NULL
            GROUP BY blood_reg_num
        """, [track_condition, track_condition, race_track_type, date] + blood_list).fetchall()
        tc_map = {r["blood_reg_num"]: (int(r["tc_n"]), int(r["tc_placed"])) for r in tc_rows_q}

        # ② 血統: pedigree から父・母父名を取得
        ped_rows = db.execute(f"""
            SELECT blood_reg_num, father_name, mat_gf_name,
                   pat_gf_name, pmgf_name
            FROM pedigree
            WHERE blood_reg_num IN ({ph})
        """, blood_list).fetchall()

        _ped_map_raw = {r["blood_reg_num"]: r for r in ped_rows}
        _all_fn  = list({r["father_name"] for r in ped_rows if r["father_name"]})
        _all_mn  = list({r["mat_gf_name"]  for r in ped_rows if r["mat_gf_name"]})
        _d7yr    = _date_sub(date, 2555)

        _SIRE_SQL = (
            "SELECT p.{col} AS sire_name, hr.track_type,"
            " CASE WHEN hr.distance <= 1400 THEN 'short'"
            "      WHEN hr.distance <= 1800 THEN 'mile'"
            "      WHEN hr.distance <= 2200 THEN 'middle'"
            "      ELSE 'long' END AS dist_bracket,"
            " hr.venue_code, COUNT(*) AS n,"
            " SUM(CASE WHEN hr.finish_pos <= 3 THEN 1 ELSE 0 END) AS places"
            " FROM horse_results hr"
            " JOIN pedigree p ON p.blood_reg_num = hr.blood_reg_num"
            " WHERE p.{col} IN ({ph2})"
            "   AND hr.race_date >= ?"
            "   AND hr.finish_pos IS NOT NULL"
            "   AND hr.track_type IN ('芝', 'ダート')"
            " GROUP BY sire_name, hr.track_type, dist_bracket, hr.venue_code"
        )
        if _all_fn:
            _fph2 = ",".join("?" * len(_all_fn))
            _f_stat_rows = db.execute(
                _SIRE_SQL.format(col="father_name", ph2=_fph2),
                _all_fn + [_d7yr]
            ).fetchall()
        else:
            _f_stat_rows = []

        if _all_mn:
            _mph2 = ",".join("?" * len(_all_mn))
            _mg_stat_rows = db.execute(
                _SIRE_SQL.format(col="mat_gf_name", ph2=_mph2),
                _all_mn + [_d7yr]
            ).fetchall()
        else:
            _mg_stat_rows = []

    # ── ② 血統スタッツをビルド ─────────────────────────────────────────────
    _father_sire_stats = _build_sire_stats(_f_stat_rows)
    _matgf_sire_stats  = _build_sire_stats(_mg_stat_rows)

    # ── インデックス（horse_histは race_date DESC 順でソート）────────────────
    horse_hist: dict[str, list] = defaultdict(list)
    for r in history:
        horse_hist[r["blood_reg_num"]].append(r)
    for blood in horse_hist:
        horse_hist[blood].sort(key=lambda r: r["race_date"], reverse=True)

    jmap = {r["jockey_code"]: r for r in j_rows}
    tmap = {r["trainer_name"]: r for r in t_rows}

    tr_map: dict[str, list] = defaultdict(list)
    for r in tr_rows:
        tr_map[r["blood_reg_num"]].append(r)

    # ── ①能力改善: メンバーレベル用バルククエリ ─────────────────────────────
    # 各馬の過去5走のレースキーを収集し、同走馬の後日グレード勝ちを確認する
    _horse_race_info: dict[str, list] = {}
    _all_member_keys: set[tuple] = set()
    for _mb in blood_list:
        _horse_race_info[_mb] = []
        for _mr in horse_hist.get(_mb, [])[:5]:
            _mk = (_mr["race_date"], _mr["venue_code"], _mr["race_num"])
            _all_member_keys.add(_mk)
            _horse_race_info[_mb].append({
                "ref_date":  _mr["race_date"],
                "key":       _mk,
                "my_pos":    _mr["finish_pos"],
                "my_margin": _mr["finish_margin"],
            })

    _race_opps_map: dict[tuple, list] = defaultdict(list)
    _opp_grade_map: dict[str, list]   = defaultdict(list)
    if _all_member_keys:
        with _db() as _mdb:
            _mcond = " OR ".join(
                "(race_date=? AND venue_code=? AND race_num=?)"
                for _ in _all_member_keys
            )
            _mparams = [p for _mk in _all_member_keys for p in _mk]
            _mopp_rows = _mdb.execute(
                f"SELECT race_date, venue_code, race_num, blood_reg_num,"
                f" finish_pos, finish_margin FROM horse_results"
                f" WHERE ({_mcond}) AND finish_pos IS NOT NULL",
                _mparams
            ).fetchall()
            _all_opp_bloods: set[str] = set()
            for _mrow in _mopp_rows:
                _mkey = (_mrow["race_date"], _mrow["venue_code"], _mrow["race_num"])
                _race_opps_map[_mkey].append({
                    "blood":  _mrow["blood_reg_num"],
                    "pos":    _mrow["finish_pos"],
                    "margin": _mrow["finish_margin"],
                })
                _all_opp_bloods.add(_mrow["blood_reg_num"])
            if _all_opp_bloods:
                _mph = ",".join("?" * len(_all_opp_bloods))
                _mgw_rows = _mdb.execute(
                    f"SELECT blood_reg_num, grade_code, race_date as win_date"
                    f" FROM horse_results WHERE blood_reg_num IN ({_mph})"
                    f" AND finish_pos=1 AND grade_code IN ('A','B','C')",
                    list(_all_opp_bloods)
                ).fetchall()
                for _mgr in _mgw_rows:
                    _opp_grade_map[_mgr["blood_reg_num"]].append(
                        (_mgr["grade_code"], _mgr["win_date"])
                    )

    # 距離（entries から取得）
    entry_dist = _f(entries[0]["distance"])

    # ⑧ トラックバイアス計算（10年・同会場・同コース・同距離帯・同馬場）
    _bias_data = _compute_bias(
        venue, race_track_type,
        entry_dist if np.isfinite(entry_dist) else 1600.0,
        track_condition, date,
    )

    # ⑩ 消しデータ閾値（toku_race_num がある重賞のみ; キャッシュ済み）
    keshi_thresholds = _keshi_thresholds(race_toku_num, date) if race_toku_num else ()

    result = []
    for e in entries:
        blood = e["blood_reg_num"]
        past  = horse_hist.get(blood, [])
        n     = len(past)

        # 過去5走
        pos_list   = [p["finish_pos"] for p in past[:5] if p["finish_pos"] is not None]
        agari_list = [p["agari_3f"]   for p in past[:5]
                      if p["agari_3f"] is not None and _f(p["agari_3f"]) >= 25]
        c4_list    = [p["corner4"]    for p in past if p["corner4"] is not None]

        pos_f   = [_f(p) for p in pos_list]   + [np.nan] * (5 - len(pos_list))
        agari_f = [_f(a) for a in agari_list] + [np.nan] * (5 - len(agari_list))

        avg_pos    = float(np.nanmean(pos_f[:5]))   if any(np.isfinite(pos_f))   else np.nan
        avg_agari  = float(np.nanmean(agari_f[:5])) if any(np.isfinite(agari_f)) else np.nan
        win_rate   = (sum(1 for p in pos_list if p == 1) / len(pos_list)) if pos_list else np.nan
        place_rate = (sum(1 for p in pos_list if p <= 3) / len(pos_list)) if pos_list else np.nan
        avg_c4     = float(np.nanmean(c4_list)) if c4_list else np.nan

        days_last  = _days_between(date, past[0]["race_date"]) if past else np.nan

        # 同会場・同コース成績
        vp   = [p for p in past if p["venue_code"] == venue and p["track_type"] == race_track_type]
        vpos = [p["finish_pos"] for p in vp if p["finish_pos"] is not None]
        venue_avg_pos  = float(np.nanmean(vpos)) if vpos else np.nan
        venue_win_rate = (sum(1 for p in vpos if p == 1) / len(vpos)) if vpos else np.nan

        # 今回レースのコース種別（train_lgbm.py の track_type_enc と一致）
        track_enc  = _f(TRACK_MAP.get(race_track_type))

        # コース適性統計（全期間）
        same_track = [p for p in past if p["track_type"] == race_track_type]
        st_pos = [p["finish_pos"] for p in same_track if p["finish_pos"] is not None]
        st_ag  = [_f(p["agari_3f"]) for p in same_track
                  if p["agari_3f"] is not None and _f(p["agari_3f"]) >= 25]
        same_track_n      = float(len(same_track))
        same_track_place  = (sum(1 for p in st_pos if p <= 3) / len(st_pos)) if st_pos else np.nan
        same_track_agari  = float(np.nanmean(st_ag)) if st_ag else np.nan

        # 同コース直近5走（スコア計算・Claude API用）
        st_recent = same_track[:5]
        stp_list  = [p["finish_pos"] for p in st_recent if p["finish_pos"] is not None]
        sta_list  = [_f(p["agari_3f"]) for p in st_recent
                     if p["agari_3f"] is not None and _f(p["agari_3f"]) >= 25]
        stp_f  = [_f(p) for p in stp_list]  + [np.nan] * (5 - len(stp_list))
        sta_f  = [_f(a) for a in sta_list]  + [np.nan] * (5 - len(sta_list))
        st_avg_pos_5    = float(np.nanmean(stp_f))  if any(np.isfinite(stp_f))  else np.nan
        st_win_rate_5   = (sum(1 for p in stp_list if p == 1) / len(stp_list)) if stp_list else np.nan
        st_avg_agari_5  = float(np.nanmean(sta_f))  if any(np.isfinite(sta_f))  else np.nan

        # 同コース直近1走の距離・着差（度外視判定用）
        _st0 = same_track[0] if same_track else None
        st_prev_distance = float(_st0["distance"]) if (_st0 and _st0["distance"]) else np.nan
        _st0_fm = _st0["finish_margin"] if _st0 else None
        _st0_lengths, _ = _decode_finish_margin(_st0_fm) if _st0_fm is not None else (None, False)
        st_prev_margin_lengths = float(_st0_lengths) if _st0_lengths is not None else np.nan

        # コース替わりフラグ（前走と今回でtrack_typeが異なれば1）
        prev_track   = next((p["track_type"] for p in past if p["track_type"]), None)
        track_switch = 0.0 if (prev_track and race_track_type and prev_track == race_track_type) else 1.0

        # 芝・ダート別成績
        turf_pos = [p["finish_pos"] for p in past
                    if p["track_type"] == "芝" and p["finish_pos"] is not None]
        dart_pos = [p["finish_pos"] for p in past
                    if p["track_type"] == "ダート" and p["finish_pos"] is not None]
        turf_n   = float(sum(1 for p in past if p["track_type"] == "芝"))
        dart_n   = float(sum(1 for p in past if p["track_type"] == "ダート"))
        turf_place_rate = (sum(1 for p in turf_pos if p <= 3) / len(turf_pos)) if turf_pos else np.nan
        dart_place_rate = (sum(1 for p in dart_pos if p <= 3) / len(dart_pos)) if dart_pos else np.nan
        turf_win_rate   = (sum(1 for p in turf_pos if p == 1) / len(turf_pos)) if turf_pos else np.nan
        dart_win_rate   = (sum(1 for p in dart_pos if p == 1) / len(dart_pos)) if dart_pos else np.nan
        turf_avg_pos    = float(np.nanmean(turf_pos)) if turf_pos else np.nan
        dart_avg_pos    = float(np.nanmean(dart_pos)) if dart_pos else np.nan

        # 騎手統計
        j     = jmap.get(e["jockey_code"])
        jr30  = int(j["rides30"] or 0) if j else 0
        jr60  = int(j["rides60"] or 0) if j else 0
        jw30  = int(j["wins30"]  or 0) if j else 0
        jp30  = int(j["places30"]or 0) if j else 0
        jw60  = int(j["wins60"]  or 0) if j else 0

        # 調教師統計
        t    = tmap.get(e["trainer_name"])
        tr30 = int(t["rides30"] or 0) if t else 0
        tr60 = int(t["rides60"] or 0) if t else 0
        tw30 = int(t["wins30"]  or 0) if t else 0
        tw60 = int(t["wins60"]  or 0) if t else 0

        # 調教データ（⑥自己比較）
        tr_list = tr_map.get(blood, [])
        if tr_list:
            latest    = tr_list[0]  # 降順ソート済み
            tr_days   = _days_between(date, latest["training_date"])
            tr_4f     = _f(latest["time_4f"])
            tr_1f     = _f(latest["time_1f_last"])
            recent14  = [r for r in tr_list if r["training_date"] >= d14]
            valid_4f  = [_f(r["time_4f"]) for r in recent14 if np.isfinite(_f(r["time_4f"]))]
            tr_avg14  = float(np.mean(valid_4f)) if valid_4f else np.nan
            tr_sess14 = float(len(recent14))

            # ⑥ 同コース自己比較: venue+pos[6]をコースグループキーとする
            _er     = (latest["extra_raw"] or "0000000000")
            _cp6    = _er[6] if len(_er) >= 7 else "0"
            _cv     = latest["venue_code"] or "00"

            if _cp6 != "0":
                # 同コースグループの過去記録（latest除く）
                _same = [
                    r for r in tr_list[1:]
                    if (r["venue_code"] or "00") == _cv
                    and len(r["extra_raw"] or "") >= 7
                    and (r["extra_raw"] or "0000000000")[6] == _cp6
                ]
                _same_4f = [_f(r["time_4f"]) for r in _same
                            if np.isfinite(_f(r["time_4f"]))]
                _same_1f = [_f(r["time_1f_last"]) for r in _same
                            if np.isfinite(_f(r["time_1f_last"]))]
                if len(_same_4f) >= 3:
                    tr_self_n       = len(_same_4f)
                    tr_self_avg_4f  = float(np.mean(_same_4f))
                    tr_self_delta_4f = tr_self_avg_4f - tr_4f   # 正=今回が速い
                    tr_self_avg_1f  = float(np.mean(_same_1f)) if len(_same_1f) >= 3 else np.nan
                    tr_self_delta_1f = (tr_self_avg_1f - tr_1f
                                        if np.isfinite(tr_self_avg_1f) and np.isfinite(tr_1f)
                                        else np.nan)
                    tr_fallback     = "self"
                else:
                    tr_self_n = len(_same_4f)
                    tr_self_avg_4f = tr_self_delta_4f = np.nan
                    tr_self_avg_1f = tr_self_delta_1f = np.nan
                    tr_fallback = "abs"
            else:
                tr_self_n = 0
                tr_self_avg_4f = tr_self_delta_4f = np.nan
                tr_self_avg_1f = tr_self_delta_1f = np.nan
                tr_fallback = "abs"
        else:
            tr_days = tr_4f = tr_1f = tr_avg14 = np.nan
            tr_sess14 = 0.0
            tr_self_n = 0
            tr_self_avg_4f = tr_self_delta_4f = np.nan
            tr_self_avg_1f = tr_self_delta_1f = np.nan
            tr_fallback = "neutral"

        # ── 馬場適性 ──────────────────────────────────────────────────────────
        _tc = tc_map.get(blood, (0, 0))
        tc_n_races  = float(_tc[0])
        tc_place_rate = (_tc[1] / _tc[0]) if _tc[0] > 0 else np.nan

        # ── 典型脚質（直近5走の最頻値、同数なら最新採用）──────────────────────
        recent_styles = [p["race_style"] for p in past[:5]
                         if p["race_style"] and p["race_style"] in "1234"]
        if recent_styles:
            _sc = {}
            for _s in recent_styles:
                _sc[_s] = _sc.get(_s, 0) + 1
            _mc = max(_sc.values())
            typical_style = next(s for s in recent_styles if _sc[s] == _mc)
        else:
            typical_style = None

        # ── トラックバイアス ──────────────────────────────────────────────────
        _sb = _bias_data.get("style_bias", {})
        _gb = _bias_data.get("gate_bias", {})
        _bias_style_exc = _sb.get(typical_style, 0.0) if (typical_style and _sb) else np.nan
        try:
            _gate_int = int(e["gate_num"] or 0)
            _br = "inner" if _gate_int <= 4 else ("middle" if _gate_int <= 8 else "outer")
            _bias_gate_exc  = _gb.get(_br, 0.0) if _gb else np.nan
        except (ValueError, TypeError):
            _bias_gate_exc = np.nan

        # ── ⑤ 消し照合スコア（今走の馬に対して適用）────────────────────────
        _prev = past[0] if past else None
        _prev_fm_raw = _prev["finish_margin"] if _prev else None
        _prev_lengths, _ = _decode_finish_margin(_prev_fm_raw) if _prev_fm_raw is not None else (None, False)
        _prev_popularity = None
        if _prev and _prev["popularity"] is not None:
            try: _prev_popularity = int(_prev["popularity"])
            except (TypeError, ValueError): pass
        _prev_grade_code = (_prev["grade_code"] or "").strip() if _prev else ""
        _prev_race_name  = (_prev["race_name"]  or "").strip() if _prev else ""

        keshi_h = {
            "prev_finish_pos":   int(_prev["finish_pos"]) if _prev else None,
            "prev_popularity":   _prev_popularity,
            "prev_margin":       float(_prev_lengths) if _prev_lengths is not None else None,
            "prev_distance":     int(_prev["distance"]) if (_prev and _prev["distance"] is not None) else None,
            "prev_track_type":   (_prev["track_type"] or "").strip() if _prev else "",
            "prev_grade_code":   _prev_grade_code,
            "prev_race_name":    _prev_race_name,
            "prev_days":         int(days_last) if np.isfinite(days_last) else None,
            "horse_age":         int(e["horse_age"]) if e["horse_age"] else None,
            "career":            n,
            "target_distance":   int(entry_dist) if np.isfinite(entry_dist) else None,
            "target_track_type": race_track_type,
        }
        keshi_score = _horse_keshi_score(keshi_h, keshi_thresholds)

        # ── ①能力改善: 5材料のδ計算 ────────────────────────────────────────────
        # 各δは「可能性の材料」として小さく。複数が同方向で揃った時だけ強評価。

        # A. クラス補正: グレード別に重み付き複勝率 vs 単純複勝率の差をスコアに換算
        _CW = {"1": 0.8, "2": 1.0, "3": 1.2, "4": 1.4, "5": 1.6}
        _GW = {"E": 1.7, "L": 1.7, "C": 1.9, "B": 2.1, "A": 2.3,
               "D": 1.8, "F": 1.9, "G": 2.1, "H": 2.3}
        _cls_tw = 0.0; _cls_wp = 0.0; _cls_n = 0; _cls_pn = 0
        for _cr in past[:10]:
            if _cr["finish_pos"] is None:
                continue
            _cg = (_cr["grade_code"] or "").strip()
            _cdc = str(_cr["dist_class"] or "")
            _cw = _GW.get(_cg) or _CW.get(_cdc, 1.0)
            _cls_tw += _cw; _cls_n += 1
            if _cr["finish_pos"] <= 3:
                _cls_wp += _cw; _cls_pn += 1
        if _cls_n > 0 and _cls_tw > 0:
            _adelta_class = float(np.clip(
                (_cls_wp / _cls_tw - _cls_pn / _cls_n) * 7.0, -1.0, 1.5
            ))
        else:
            _adelta_class = 0.0

        # B. 着差補正: 着外(4着以下)時の平均着差で「惜しい負け」か「大差」かを区別
        _umargs: list[float] = []
        for _br in past[:5]:
            if _br["finish_pos"] is None or _br["finish_pos"] <= 3:
                continue
            _bmv, _ = _decode_finish_margin(_br["finish_margin"])
            if _bmv is not None:
                _umargs.append(_bmv)
        if _umargs:
            _avg_um = float(np.mean(_umargs))
            if   _avg_um <= 1.0: _adelta_margin =  0.5
            elif _avg_um <= 2.0: _adelta_margin =  0.2
            elif _avg_um <= 4.0: _adelta_margin =  0.0
            elif _avg_um <= 8.0: _adelta_margin = -0.3
            else:                _adelta_margin = -0.5
        else:
            _adelta_margin = 0.0

        # C. メンバーレベル補正: 同走馬が後日グレード勝ちした場合に弱加点
        _MBPLA = {"A": 0.4, "B": 0.3, "C": 0.2}
        _MBMRG = {"A": 0.3, "B": 0.2, "C": 0.1}
        _mem_acc = 0.0
        for _ri in _horse_race_info.get(blood, []):
            _rdt = _ri["ref_date"]
            _rmp = _ri["my_pos"]
            _rmv, _ = _decode_finish_margin(_ri["my_margin"]) if _ri["my_margin"] else (None, False)
            for _opp in _race_opps_map.get(_ri["key"], []):
                if _opp["blood"] == blood:
                    continue
                _best_gc: str | None = None
                for _gc, _wd in _opp_grade_map.get(_opp["blood"], []):
                    if _wd > _rdt and (_best_gc is None or _gc < _best_gc):
                        _best_gc = _gc
                if _best_gc is None:
                    continue
                if _rmp is not None and _rmp <= 3:
                    _mem_acc += _MBPLA.get(_best_gc, 0.0)
                elif _rmv is not None and _rmv <= 1.0:
                    _mem_acc += _MBMRG.get(_best_gc, 0.0)
        _adelta_member = float(np.clip(_mem_acc, 0.0, 1.0))

        # D. 上がり3F補正: 距離・競馬場込みの末脚傾向(あくまで可能性の材料、上限+0.5)
        _adelta_agari = 0.0
        _td = float(entry_dist) if np.isfinite(entry_dist) else 0.0
        # (1) 今日以上の距離・同コースで上がり良好経験 → 距離適性の可能性
        _ag_thr = 34.5 if race_track_type == "芝" else 37.5
        for _dr in past:
            _dag = _f(_dr["agari_3f"])
            if (np.isfinite(_dag) and _dag >= 25 and _dag <= _ag_thr
                    and _f(_dr["distance"] or 0) >= _td
                    and (_dr["track_type"] or "") == race_track_type):
                _adelta_agari = max(_adelta_agari, 0.2)
                break
        # (2) 長直競馬場(東京05/新潟04)で上がり良好 かつ 今日も同会場
        if venue in ("05", "04"):
            for _dr in past:
                if (_dr["venue_code"] or "") not in ("05", "04"):
                    continue
                _dag = _f(_dr["agari_3f"])
                if np.isfinite(_dag) and 25 <= _dag <= _ag_thr:
                    _adelta_agari = min(0.5, _adelta_agari + 0.2)
                    break
        # (3) 逃/先行馬で上がり良好 → 持続力優秀の可能性(最も強い材料)
        _fa = [_f(_dr["agari_3f"]) for _dr in past[:5]
               if (_dr["race_style"] or "") in ("1", "2")
               and _dr["agari_3f"] and _f(_dr["agari_3f"]) >= 25]
        if _fa and float(np.mean(_fa)) <= _ag_thr:
            _adelta_agari = min(0.5, _adelta_agari + 0.3)
        _adelta_agari = float(np.clip(_adelta_agari, 0.0, 0.5))

        # E. 格降格補正: 過去3走に高グレードレースがあり今日が大幅格下 → 弱加点
        _GL = {"A": 5, "B": 4, "C": 3, "L": 2, "E": 2, "D": 3, "G": 3, "H": 4, "F": 3}
        _today_gl    = _GL.get(_grade, 0)
        _past_max_gl = max(
            (_GL.get((_pr["grade_code"] or "").strip(), 0) for _pr in past[:3]),
            default=0
        )
        _gg = _past_max_gl - _today_gl
        if   _gg >= 3: _adelta_grade_drop = 0.6
        elif _gg >= 2: _adelta_grade_drop = 0.4
        elif _gg >= 1: _adelta_grade_drop = 0.2
        else:          _adelta_grade_drop = 0.0

        # ── ② 血統適性スコアの計算 (B案: 相対70% + 絶対30%) ─────────────────
        _ped     = _ped_map_raw.get(blood)
        _f_nm    = (_ped["father_name"] or "") if _ped else ""
        _mg_nm   = (_ped["mat_gf_name"]  or "") if _ped else ""

        _today_db = ("short"  if np.isfinite(entry_dist) and entry_dist <= 1400 else
                     "mile"   if np.isfinite(entry_dist) and entry_dist <= 1800 else
                     "middle" if np.isfinite(entry_dist) and entry_dist <= 2200 else
                     "long"   if np.isfinite(entry_dist) else "mile")

        _f_dr, _f_vr   = _sire_ratios(_f_nm,  race_track_type, _today_db, venue, _father_sire_stats)
        _mg_dr, _mg_vr = _sire_ratios(_mg_nm, race_track_type, _today_db, venue, _matgf_sire_stats)

        # 相対評価: 父80%(dist40%+venue40%) + 母父20%(dist10%+venue10%)
        _s2_rel = 5.0 * (0.40 * _f_dr + 0.40 * _f_vr + 0.10 * _mg_dr + 0.10 * _mg_vr)

        # 絶対評価: 同コース種別の産駒全体複勝率 vs グローバル実測値
        # n<30の種牡馬は中立(5.0)。全産駒・全条件ではなく同コース種別に限定
        # (全条件だと芝/マイル専門の父がダート戦でも高評価になるため)
        _s2_abs_f  = _sire_abs_score(_f_nm,  race_track_type, _father_sire_stats)
        _s2_abs_mg = _sire_abs_score(_mg_nm, race_track_type, _matgf_sire_stats)
        _s2_abs = 0.80 * _s2_abs_f + 0.20 * _s2_abs_mg  # 父80% 母父20%

        # B案合成: 相対70% + 絶対30%
        _s2_raw = float(np.clip(0.70 * _s2_rel + 0.30 * _s2_abs, 1.0, 10.0))

        # 手動血統注入(純粋上書き): 入力があれば統計②を無視
        _manual_s2 = _get_manual_s2(date, venue, race_num, e["horse_num"])
        if _manual_s2 is not None:
            _s2_raw = _manual_s2

        result.append({
            # meta（モデル特徴量以外）
            "horse_num":    e["horse_num"],
            "gate_num":     e["gate_num"] or "",
            "horse_name":   e["horse_name"] or "",
            "jockey_name":  e["jockey_name"] or "",
            "trainer_name": e["trainer_name"] or "",
            "_sex_code":    e["sex_code"] or "",
            "_horse_age":   e["horse_age"],
            # モデル特徴量
            "distance":          entry_dist,
            "track_type_enc":    track_enc,
            "venue_int":         _f(venue),
            "horse_pos_1":       pos_f[0],
            "horse_pos_2":       pos_f[1],
            "horse_pos_3":       pos_f[2],
            "horse_pos_4":       pos_f[3],
            "horse_pos_5":       pos_f[4],
            "horse_agari_1":     agari_f[0],
            "horse_agari_2":     agari_f[1],
            "horse_agari_3":     agari_f[2],
            "horse_agari_4":     agari_f[3],
            "horse_agari_5":     agari_f[4],
            "horse_avg_pos_5":   avg_pos,
            "horse_win_rate_5":  win_rate,
            "horse_place_rate_5": place_rate,
            "horse_avg_agari_5": avg_agari,
            "horse_n_races":     float(n),
            "horse_days_last_race": days_last,
            "horse_avg_corner4": avg_c4,
            "horse_venue_avg_pos":  venue_avg_pos,
            "horse_venue_win_rate": venue_win_rate,
            "horse_venue_races":    float(len(vp)),
            "gate_num_int":     _f(e["gate_num"]),
            "horse_num_int":    _f(e["horse_num"]),
            "starters":         float(starters),
            "horse_age_int":    _f(e["horse_age"]),
            "sex_enc":          _f(SEX_MAP.get(e["sex_code"] or "")),
            "horse_weight":     _f(e["body_weight"]),
            "weight_change_int": np.nan,
            "jockey_win30":   jw30 / jr30 if jr30 > 0 else np.nan,
            "jockey_place30": jp30 / jr30 if jr30 > 0 else np.nan,
            "jockey_rides30": float(jr30),
            "jockey_win60":   jw60 / jr60 if jr60 > 0 else np.nan,
            "trainer_win30":  tw30 / tr30 if tr30 > 0 else np.nan,
            "trainer_win60":  tw60 / tr60 if tr60 > 0 else np.nan,
            "tr_days_before":  tr_days,
            "tr_4f_last":      tr_4f,
            "tr_1f_last":      tr_1f,
            "tr_4f_avg14d":    tr_avg14,
            "tr_sessions_14d": tr_sess14,
            # ⑥ 自己比較フィールド
            "_tr_self_n":        float(tr_self_n),
            "_tr_self_avg_4f":   tr_self_avg_4f,
            "_tr_self_delta_4f": tr_self_delta_4f,
            "_tr_self_delta_1f": tr_self_delta_1f,
            "_tr_fallback":      tr_fallback,
            # コース適性（モデル特徴量外・表示/Claude API用）
            "same_track_place_rate": same_track_place,
            "same_track_n_races":    same_track_n,
            "same_track_avg_agari":  same_track_agari,
            "track_switch":          track_switch,
            "turf_place_rate":       turf_place_rate,
            "turf_win_rate":         turf_win_rate,
            "turf_avg_pos":          turf_avg_pos,
            "turf_n_races":          turf_n,
            "dart_place_rate":       dart_place_rate,
            "dart_win_rate":         dart_win_rate,
            "dart_avg_pos":          dart_avg_pos,
            "dart_n_races":          dart_n,
            "_race_track_type":      race_track_type,
            # 同コース直近5走（スコア計算に使用）
            "st_pos_1": stp_f[0], "st_pos_2": stp_f[1], "st_pos_3": stp_f[2],
            "st_pos_4": stp_f[3], "st_pos_5": stp_f[4],
            "st_agari_1": sta_f[0], "st_agari_2": sta_f[1], "st_agari_3": sta_f[2],
            "st_agari_4": sta_f[3], "st_agari_5": sta_f[4],
            "st_avg_pos_5":   st_avg_pos_5,
            "st_win_rate_5":  st_win_rate_5,
            "st_avg_agari_5": st_avg_agari_5,
            "st_prev_distance":       st_prev_distance,
            "st_prev_margin_lengths": st_prev_margin_lengths,
            # 馬場適性・バイアス（スコア計算用）
            "tc_n_races":       tc_n_races,
            "tc_place_rate":    tc_place_rate,
            "_typical_style":   typical_style or "",
            "_bias_style_exc":  _bias_style_exc,
            "_bias_gate_exc":   _bias_gate_exc,
            "_track_condition": track_condition,
            "_bias_n_total":    float(_bias_data.get("n_total", 0)),
            "_bias_stage":      _bias_data.get("bias_stage", "5"),
            # ③環境: 馬番別ベイズ調整複勝率 (枠番でなく馬番で集計)
            "_horse_num_adj_rate": _bias_data.get("horse_num_rates", {}).get(
                int(e["horse_num"] or 0) if e["horse_num"] else 0, np.nan),
            "_horse_num_prior":    float(_bias_data.get("horse_num_prior", np.nan)),
            # ⑤ 消し照合スコア（precomputed）
            "_keshi_score":     keshi_score,
            # ①能力改善δ（_compute_scoresで使用）
            "ability_delta_class":      _adelta_class,
            "ability_delta_margin":     _adelta_margin,
            "ability_delta_member":     _adelta_member,
            "ability_delta_agari":      _adelta_agari,
            "ability_delta_grade_drop": _adelta_grade_drop,
            # ②血統適性スコア（_compute_scoresで使用）
            "s2_bloodline":   _s2_raw,
            "_father_name":   _f_nm,
            "_matgf_name":    _mg_nm,
            "_s2_dist_bracket": _today_db,
        })

    # ③環境: メンバー構成から想定ペース判定
    # 前に行く馬(逃げ=1 + 先行=2)の割合で分類
    # スタイルデータが出走頭数の50%未満なら判定不能→平均扱い
    _n_front      = sum(1 for f in result if f.get("_typical_style") in ("1", "2"))
    _n_with_style = sum(1 for f in result if f.get("_typical_style") in ("1", "2", "3", "4"))
    _n_total      = len(result)
    if _n_with_style >= max(2, _n_total // 2):
        # 出走頭数の半数以上のスタイルが分かる場合のみ判定
        _front_ratio = _n_front / _n_total
        if _front_ratio > 0.50:
            _pace_type = "ハイ"
        elif _front_ratio < 0.30:
            _pace_type = "スロー"
        else:
            _pace_type = "平均"
    else:
        _front_ratio = float(_n_front) / _n_total if _n_total > 0 else 0.0
        _pace_type   = "平均"  # データ不足 → 中立
    for f in result:
        f["_race_pace_type"]   = _pace_type
        f["_race_front_ratio"] = _front_ratio
        f["_race_n_front"]     = _n_front

    return result


# ── 6. 予想エンドポイント ─────────────────────────────────────────────────────

@app.get("/api/prediction")
def get_prediction(
    date:  str = Query(...),
    venue: str = Query(...),
    race:  str = Query(...),
    day_num: Optional[str] = Query(None),
    track_condition: Optional[str] = Query(default=None),
):
    cache_key = f"{date}:{venue}:{race}"
    if cache_key in _prediction_cache:
        return Response(content=_prediction_cache[cache_key], media_type="application/json")

    if _model is None:
        raise HTTPException(503, "Model not loaded")

    feats = _build_features(date, venue, race, track_condition)
    if not feats:
        raise HTTPException(404, "Race not found or no entries")

    X     = np.array([[f[col] for col in FEATURES] for f in feats], dtype=float)
    probs = _model.predict(X)

    # 全馬のスコアを先に計算（複合スコアに必要）
    all_scores      = [_compute_scores(f) for f in feats]
    all_totals      = [sum(s.values()) for s in all_scores]

    # 複合スコア = prob × (total/60)^COMPOSITE_ALPHA で印を決める
    composite = np.array([
        float(probs[i]) * (all_totals[i] / 60.0) ** COMPOSITE_ALPHA
        for i in range(len(feats))
    ])
    order   = np.argsort(-composite)          # 複合スコア降順
    rank_of = {int(idx): int(pos) for pos, idx in enumerate(order)}

    MARK_BY_RANK = {0: "◎", 1: "○", 2: "▲", 3: "△", 4: "△", 5: "△"}
    SEX_JP = {"1": "牡", "2": "牝", "3": "騸", "10": "牡", "20": "牝", "30": "騸"}

    horses = []
    for i, f in enumerate(feats):
        model_rank  = rank_of[i]
        prob_pct    = round(float(probs[i]) * 100, 1)
        scores      = all_scores[i]
        total_score = all_totals[i]
        horses.append({
            "model_rank":   model_rank + 1,
            "horse_num":    f["horse_num"],
            "gate_num":     f["gate_num"],
            "horse_name":   f["horse_name"],
            # DBではjockey_nameとtrainer_nameが逆に格納されているため表示用にスワップ
            "jockey_name":  f["trainer_name"],
            "trainer_name": f["jockey_name"],
            "sex":          SEX_JP.get(f.get("_sex_code", ""), ""),
            "horse_age":    f.get("_horse_age", ""),
            "mark":         MARK_BY_RANK.get(model_rank, ""),
            "prob":         prob_pct,
            "scores":       scores,
            "total_score":  total_score,
            "actual_pos":   None,
            "past_5": [
                {
                    "pos":   int(f[f"horse_pos_{k}"]) if np.isfinite(f[f"horse_pos_{k}"]) else None,
                    "agari": round(float(f[f"horse_agari_{k}"]), 1)
                              if np.isfinite(f[f"horse_agari_{k}"]) else None,
                }
                for k in range(1, 6)
            ],
        })

    # レース情報（entriesから）+ track_type確定後にcommentを追加
    with _db() as db:
        meta = db.execute("""
            SELECT MAX(race_name) race_name, MAX(distance) distance,
                   MAX(grade_code) grade_code, MAX(day_num) day_num
            FROM entries WHERE race_date=? AND venue_code=? AND race_num=?
        """, (date, venue, race)).fetchone()
        tt = _get_track_type(venue, meta["distance"] if meta else None, db)

    for i, h in enumerate(horses):
        h["comment"] = _generate_comment(feats[i], h["scores"], tt)

    top6     = [horses[i]["horse_num"] for i in order[:6]]
    top3     = top6[:3]
    tickets  = _tickets(top3)

    # recommendations（フロントエンド互換）
    MARK_LABELS = {"◎": "本命", "○": "対抗", "▲": "単穴"}
    # 確率降順（model_rank 昇順）で並べる
    marks = sorted(
        [
            {
                "mark":       h["mark"],
                "label":      MARK_LABELS[h["mark"]],
                "horse_num":  h["horse_num"],
                "horse_name": h["horse_name"],
                "prob":       h["prob"],
            }
            for h in horses if h["mark"] in MARK_LABELS
        ],
        key=lambda x: x["prob"], reverse=True,
    )
    himo = sorted(
        [
            {"horse_num": h["horse_num"], "horse_name": h["horse_name"], "prob": h["prob"]}
            for h in horses if h["mark"] == "△"
        ],
        key=lambda x: x["prob"], reverse=True,
    )

    result = {
        "race_info": {
            "date":       date,
            "venue_code": venue,
            "venue_name": VENUE_NAMES.get(venue, venue),
            "race_num":   race,
            "day_num":    meta["day_num"] if meta else "",
            "race_name":  (meta["race_name"] or f"{race}R").strip() if meta else f"{race}R",
            "distance":   meta["distance"] if meta else None,
            "grade_code": (meta["grade_code"] or "").strip() if meta else "",
            "starters":   len(feats),
            "track_type": tt,
        },
        "horses": horses,
        "recommendations": {
            "marks":     marks,
            "himo":      himo,
            "longshots": [],
            "tickets":   tickets,
        },
        "top3_nums": top3,
    }
    result_bytes = _json_bytes(result)
    _prediction_cache[cache_key] = result_bytes
    return Response(content=result_bytes, media_type="application/json")


def _compute_scores(f: dict) -> dict[str, int]:
    """設計書6項目スコア（①〜⑥ 各1-10点、合計60点満点）。"""
    dist       = _f(f.get("distance", np.nan))
    avg_agari  = _f(f.get("horse_avg_agari_5"))
    n_races    = _f(f.get("horse_n_races", 0))
    v_win_rate = _f(f.get("horse_venue_win_rate"))
    v_avg_pos  = _f(f.get("horse_venue_avg_pos"))
    v_races    = _f(f.get("horse_venue_races", 0))
    gate       = _f(f.get("gate_num_int"))
    avg_c4     = _f(f.get("horse_avg_corner4"))
    starters   = _f(f.get("starters", 10))
    tr_days    = _f(f.get("tr_days_before"))
    tr_4f      = _f(f.get("tr_4f_last"))
    tr_1f      = _f(f.get("tr_1f_last"))
    tr_sess    = _f(f.get("tr_sessions_14d", 0))

    st_n          = _f(f.get("same_track_n_races", 0))
    st_place_rate = _f(f.get("same_track_place_rate"))
    st_avg_pos    = _f(f.get("st_avg_pos_5"))
    st_avg_agari  = _f(f.get("st_avg_agari_5"))
    st_win_rate   = _f(f.get("st_win_rate_5"))
    use_st = np.isfinite(st_place_rate) and st_n >= 3

    race_tt = f.get("_race_track_type", "")
    if race_tt == "芝":
        fb_place = _f(f.get("turf_place_rate"));  fb_win = _f(f.get("turf_win_rate"));  fb_pos = _f(f.get("turf_avg_pos"))
    elif race_tt == "ダート":
        fb_place = _f(f.get("dart_place_rate"));  fb_win = _f(f.get("dart_win_rate"));  fb_pos = _f(f.get("dart_avg_pos"))
    else:
        fb_place = _f(f.get("horse_place_rate_5")); fb_win = _f(f.get("horse_win_rate_5")); fb_pos = _f(f.get("horse_avg_pos_5"))

    eff_place = st_place_rate if use_st else fb_place
    eff_pos   = st_avg_pos    if (use_st and np.isfinite(st_avg_pos))   else fb_pos
    eff_agari = st_avg_agari  if (use_st and np.isfinite(st_avg_agari)) else avg_agari
    eff_win   = st_win_rate   if (use_st and np.isfinite(st_win_rate))  else fb_win

    def clamp(x: float, lo: int = 1, hi: int = 10) -> int:
        return int(round(float(np.clip(x, lo, hi))))

    # ===========================================================
    # ① 能力 (1-10): 複勝率×7.0 + 着順ボーナス + 馬場適性delta + 改善5材料delta
    # win×2.0・agari_bonusは複勝予想では「一発屋」を過剰評価するため除外
    # ===========================================================
    # 改善5材料δを読み取る（大原則: 各材料は可能性として弱め。複数同方向で初めて強評価）
    _s1_dc = float(f.get("ability_delta_class",      0.0) or 0.0)
    _s1_dm = float(f.get("ability_delta_margin",     0.0) or 0.0)
    _s1_mb = float(f.get("ability_delta_member",     0.0) or 0.0)
    _s1_ag = float(f.get("ability_delta_agari",      0.0) or 0.0)
    _s1_gd = float(f.get("ability_delta_grade_drop", 0.0) or 0.0)
    _s1_improvement = _s1_dc + _s1_dm + _s1_mb + _s1_ag + _s1_gd

    if np.isfinite(eff_place):
        s1 = (
            eff_place * 7.0
            + (max(0.0, (5.0 - eff_pos) * 0.5) if np.isfinite(eff_pos) else 0.0)
        )
        s1 = max(2.0, s1)
    else:
        # データなし = 「不明」。5(平均)ではなく3.0で保守的に扱う
        s1 = 3.0

    # 馬場適性 delta（±2）→ ①能力に加算
    tc_n     = int(_f(f.get("tc_n_races", 0)) or 0)
    tc_place = _f(f.get("tc_place_rate"))
    if race_tt == "芝":
        fb_tc   = _f(f.get("turf_place_rate")); fb_tc_n = int(_f(f.get("turf_n_races", 0)) or 0)
    else:
        fb_tc   = _f(f.get("dart_place_rate")); fb_tc_n = int(_f(f.get("dart_n_races", 0)) or 0)
    if tc_n >= 3 and np.isfinite(tc_place):        ref_tc = tc_place
    elif fb_tc_n >= 3 and np.isfinite(fb_tc):      ref_tc = fb_tc
    else:                                           ref_tc = None
    if ref_tc is not None:
        if ref_tc >= 0.40:   surface_delta = 2
        elif ref_tc >= 0.30: surface_delta = 1
        elif ref_tc >= 0.20: surface_delta = 0
        elif ref_tc >= 0.10: surface_delta = -1
        else:                surface_delta = -2
    else:
        surface_delta = 0

    # 前走大敗ペナルティ（同コース直近1走）
    st_pos_1 = _f(f.get("st_pos_1"))
    if np.isfinite(st_pos_1):
        if st_pos_1 > 12:
            s1 = max(1.0, s1 * 0.55)
        elif st_pos_1 > 8:
            s1 = max(1.0, s1 * 0.75)
        elif st_pos_1 > 5:
            _prev_dist   = _f(f.get("st_prev_distance"))
            _prev_margin = _f(f.get("st_prev_margin_lengths"))
            _cond_a = (np.isfinite(_prev_dist) and abs(_prev_dist - dist) >= 400
                       and np.isfinite(_prev_margin) and _prev_margin <= 3.0)
            _cond_b = np.isfinite(_prev_margin) and _prev_margin <= 1.5
            if not (_cond_a or _cond_b):
                s1 = max(1.0, s1 * 0.88)

    s1 = clamp(s1 + surface_delta + _s1_improvement)

    # ===========================================================
    # ② 血統 (1-10): pedigreeベースの父/母父×距離帯/会場の複勝率比率
    # 上がり3F代理は廃止。比率=1.0(実績なし)→ s2=5(中立)。
    # ===========================================================
    s2_bl = float(f.get("s2_bloodline", 5.0) or 5.0)
    s2 = clamp(s2_bl)

    # ===========================================================
    # ③ レース環境 (1-10): 4成分加重平均
    #   会場実績0.30 + 展開適合0.30 + 馬番有利不利0.20 + 馬場状態0.20
    # ===========================================================

    # 成分A: 会場実績 (s_venue)
    if np.isfinite(v_win_rate) and v_races >= 2:
        s_venue = 5.0 + v_win_rate * 5.0
        if np.isfinite(v_avg_pos):
            s_venue += max(-2.0, (4.0 - v_avg_pos) * 0.5)
    elif np.isfinite(eff_place):
        s_venue = 3.0 + eff_place * 4.0
    else:
        s_venue = 5.0
    s_venue = float(np.clip(s_venue, 1, 10))

    # 成分B: 展開適合 (s_pace_new) — メンバー構成ベース
    # _race_pace_type は _build_features 末尾で全馬に付与
    PACE_TABLE: dict[str, dict[str, float]] = {
        "ハイ":   {"1": 4.0, "2": 4.5, "3": 6.5, "4": 7.0},
        "スロー": {"1": 7.0, "2": 6.5, "3": 4.5, "4": 4.0},
        "平均":   {"1": 5.0, "2": 5.5, "3": 5.0, "4": 5.0},
    }
    _pace_type  = f.get("_race_pace_type", "平均")
    _this_style = f.get("_typical_style", "")
    s_pace_new  = PACE_TABLE.get(_pace_type, PACE_TABLE["平均"]).get(_this_style, 5.0)

    # 成分C: 馬番×コース有利不利 (s_gate_new) — 枠番でなく馬番ベース
    _gate_adj   = _f(f.get("_horse_num_adj_rate"))
    _gate_prior = _f(f.get("_horse_num_prior"))
    if np.isfinite(_gate_adj) and np.isfinite(_gate_prior) and _gate_prior > 0:
        _gate_dev = _gate_adj - _gate_prior
        s_gate_new = float(np.clip(5.0 + _gate_dev * 20.0, 1, 10))
    else:
        s_gate_new = 5.0

    # 成分D: 馬場状態実績 (s_ground)
    tc_n     = int(_f(f.get("tc_n_races", 0)) or 0)
    tc_place = _f(f.get("tc_place_rate"))
    if tc_n >= 3 and np.isfinite(tc_place) and np.isfinite(eff_place):
        _ground_dev = tc_place - eff_place
        s_ground = float(np.clip(5.0 + _ground_dev * 10.0, 1, 10))
    elif tc_n >= 3 and np.isfinite(tc_place):
        _ground_dev = tc_place - 0.33
        s_ground = float(np.clip(5.0 + _ground_dev * 8.0, 1, 10))
    else:
        s_ground = 5.0

    s3 = clamp(0.30 * s_venue + 0.30 * s_pace_new + 0.20 * s_gate_new + 0.20 * s_ground)

    # ===========================================================
    # ④ バイアス (1-9): 0.7*脚質 + 0.3*枠, スケール×15, 中立=5
    # 脚質のみ有効な場合も計算可(枠データなしでも脚質だけで評価)
    # ===========================================================
    bias_style_exc = _f(f.get("_bias_style_exc"))
    bias_gate_exc  = _f(f.get("_bias_gate_exc"))
    if np.isfinite(bias_style_exc) and np.isfinite(bias_gate_exc):
        raw_bias = 0.7 * bias_style_exc + 0.3 * bias_gate_exc
    elif np.isfinite(bias_style_exc):
        raw_bias = bias_style_exc   # 枠データなし → 脚質のみ
    else:
        raw_bias = np.nan
    if np.isfinite(raw_bias):
        s4 = int(round(float(np.clip(5.0 + raw_bias * 15, 1, 9))))
    else:
        s4 = 5
    # データなし馬(①中立)のバイアス上限: 実績なしでバイアスだけ浮上するのを防ぐ
    if not np.isfinite(eff_place) and s4 > 6:
        s4 = 6

    # ===========================================================
    # ⑤ 照合 (2-10): 消しデータ連携（_build_featuresで計算済み）
    # ===========================================================
    s5 = max(2, min(10, int(f.get("_keshi_score", 5))))

    # ===========================================================
    # ===========================================================
    # ⑥ 調教 (1-10): 同コース自己比較主軸 + 直近性 + 本数
    # 主パス: 同venue+pos[6]でn>=3 → 自己平均との差でスコア化
    # フォールバック(abs): 絶対値評価(精度低い→幅を4-6点に狭める)
    # フォールバック(neutral): データなし → 5.0
    # 1Fは補助: ±0.3の微調整のみ
    # ===========================================================
    tr_self_delta_4f = _f(f.get("_tr_self_delta_4f"))
    tr_self_delta_1f = _f(f.get("_tr_self_delta_1f"))
    tr_fallback      = f.get("_tr_fallback", "neutral")

    if tr_fallback == "self" and np.isfinite(tr_self_delta_4f):
        # 主パス: 自己比較 (range 3-7: ±2点, キャップ±4s)
        delta_c = float(np.clip(tr_self_delta_4f, -4.0, 4.0))
        s6 = float(np.clip(5.0 + delta_c * 0.5, 3.0, 7.0))
        # 1Fラスト補助: ±0.3以内の微調整
        if np.isfinite(tr_self_delta_1f):
            adj_1f = float(np.clip(tr_self_delta_1f * 0.3, -0.3, 0.3))
            s6 = float(np.clip(s6 + adj_1f, 3.0, 7.0))
    elif tr_fallback == "abs" and np.isfinite(tr_4f) and tr_4f > 0:
        # 絶対値フォールバック: 精度低いため幅を4-6点に狭める
        s6_raw = (62.0 - tr_4f) / 6.0  # スケール変更: ±1点/6秒
        s6 = float(np.clip(5.0 + s6_raw, 4.0, 6.0))
    else:
        # データなし: 中立
        s6 = 5.0

    # 直近性補正 (±0.5以内)
    if np.isfinite(tr_days):
        if tr_days <= 7:
            s6 = min(10.0, s6 + 0.5)
        elif tr_days > 21:
            s6 = max(1.0, s6 - 0.5)
    # 本数補正 (直近14日)
    if tr_sess >= 3:
        s6 = min(10.0, s6 + 0.5)

    return {
        "ability":     s1,           # ① 能力
        "bloodline":   s2,           # ② 血統
        "environment": s3,           # ③ 環境
        "bias":        s4,           # ④ バイアス
        "keshi":       s5,           # ⑤ 照合
        "training":    clamp(s6),    # ⑥ 調教
    }


def _generate_comment(f: dict, scores: dict, track_type: str) -> str:
    """スコアと特徴量から200字程度の解説文を生成する。"""
    ability   = scores["ability"]
    bloodline = scores["bloodline"]
    env       = scores["environment"]
    pace      = scores["environment"]   # ③環境に統合
    history   = scores["keshi"]         # ⑤照合を代替使用
    training  = scores["training"]

    dist       = _f(f.get("distance", np.nan))
    avg_agari  = _f(f.get("horse_avg_agari_5"))
    place_rate = _f(f.get("horse_place_rate_5"))
    win_rate   = _f(f.get("horse_win_rate_5"))
    n_races    = _f(f.get("horse_n_races", 0))
    gate       = _f(f.get("gate_num_int"))
    avg_c4     = _f(f.get("horse_avg_corner4"))
    starters   = _f(f.get("starters", 10))
    tr_days    = _f(f.get("tr_days_before"))
    tr_4f      = _f(f.get("tr_4f_last"))
    v_win_rate = _f(f.get("horse_venue_win_rate"))
    v_races    = _f(f.get("horse_venue_n_races", 0))

    tt  = track_type or "この条件"
    dst = f"{int(dist)}m" if np.isfinite(dist) and dist > 0 else ""
    parts: list[str] = []

    # ① 能力・実績
    if not np.isfinite(place_rate) or n_races < 1:
        parts.append("初出走または実績データ不足で未知の能力を秘める")
    elif ability >= 8:
        agari_str = f"上がり3F平均{avg_agari:.1f}秒" if np.isfinite(avg_agari) and avg_agari > 0 else "高い末脚"
        wr = f"・勝率{int(win_rate*100)}%" if np.isfinite(win_rate) else ""
        parts.append(f"【能力】{agari_str}{wr}と実力は最上位クラス")
    elif ability >= 6:
        rate_str = f"複勝率{int(place_rate*100)}%" if np.isfinite(place_rate) else "安定した成績"
        parts.append(f"【能力】{rate_str}で堅実な走りが持ち味")
    else:
        parts.append("【能力】近走成績はやや物足りず上位争いへの壁は厚い")

    # ② 血統・コース・距離適性
    if bloodline >= 8:
        parts.append(f"【血統】{tt}{dst}への適性は最高クラスで条件は完璧に合致")
    elif bloodline >= 6 and env >= 6:
        v_str = f"・当会場{int(v_win_rate*100)}%の実績" if np.isfinite(v_win_rate) and np.isfinite(v_races) and v_races >= 2 else ""
        parts.append(f"【血統】{tt}{dst}に合った適性{v_str}で条件は前向き")
    elif bloodline <= 3:
        parts.append(f"【血統】{tt}{dst}への血統的な裏付けは薄く距離適性に不安")
    elif env <= 3 and np.isfinite(v_races) and v_races >= 2:
        parts.append("【環境】この会場での成績が芳しくなくコース適性に懸念")
    else:
        parts.append(f"【血統】{tt}への適性は標準的で大きなプラスマイナスなし")

    # ③ 展開・脚質
    if np.isfinite(avg_c4) and np.isfinite(starters) and starters > 0:
        c4_pct = avg_c4 / starters
        style  = "先行" if c4_pct < 0.3 else ("追い込み" if c4_pct > 0.65 else "差し")
        gate_str = "内枠の利を活かした" if np.isfinite(gate) and gate <= 2 else \
                   "外枠のハンデを抱える" if np.isfinite(gate) and gate >= 8 else ""
        if pace >= 7:
            parts.append(f"【展開】{gate_str}{style}の脚質が今日のペース想定に合致し好走期待")
        elif pace <= 3:
            parts.append(f"【展開】{gate_str}{style}だが展開が向かない公算が高く苦戦の懸念")
        else:
            parts.append(f"【展開】{gate_str}{style}の競馬で流れ次第の面がある")
    elif np.isfinite(gate) and gate >= 8:
        parts.append("【展開】外枠スタートで先行馬にはポジション確保が課題")
    else:
        parts.append("【展開】展開データ不足のため脚質評価は不透明")

    # ④ 調教・過去データ
    if training >= 8:
        tr_str = f"4F{tr_4f:.1f}秒の好タイムを記録し" if np.isfinite(tr_4f) and tr_4f > 0 else ""
        parts.append(f"【調教】{tr_str}仕上がり抜群。過去データも良好で当日の気配に期待")
    elif history >= 7 and training >= 5:
        parts.append(f"【調教】状態は良好。過去の好走実績も豊富で安定した走りが見込める")
    elif training <= 3:
        if np.isfinite(tr_days) and tr_days > 21:
            parts.append(f"【調教】前走から{int(tr_days)}日の間隔で調教量が不足、仕上がり面に不安")
        else:
            parts.append("【調教】調教データが乏しく仕上がり状態は判断困難")
    elif history <= 3:
        parts.append("【過去】好走実績が少なく信頼度は低め。穴候補としての一考はあり")
    else:
        parts.append("【調教】平均的な仕上がりで過去データも標準的な評価")

    if not parts:
        return "総合的に平均的な評価。当日の気配・馬場状態次第の面がある。"

    comment = "。".join(parts[:4]) + "。"
    return comment[:230] if len(comment) <= 230 else comment[:228] + "…"


def _tickets(top3: list[str]) -> list[dict]:
    t = []
    if len(top3) >= 1:
        t.append({"type": "単勝",   "desc": f"単勝 {top3[0]}"})
    if len(top3) >= 2:
        t.append({"type": "馬連",   "desc": f"馬連 {top3[0]}-{top3[1]}"})
        t.append({"type": "ワイド", "desc": f"ワイド {top3[0]}-{top3[1]}"})
    if len(top3) >= 3:
        t.append({"type": "3連複",  "desc": f"3連複 {top3[0]}-{top3[1]}-{top3[2]} BOX"})
        t.append({"type": "3連単",  "desc": f"3連単 {top3[0]}→{top3[1]}→{top3[2]}"})
    return t


# ── 静的ファイル配信 ──────────────────────────────────────────────────────────

_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
