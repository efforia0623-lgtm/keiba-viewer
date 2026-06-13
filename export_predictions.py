"""
予想結果を JSON ファイルに出力するスクリプト。
Claude API で展開予想・スコア・解説文を生成。

Usage:
    python export_predictions.py              # 最新日付（entries の最大日）
    python export_predictions.py 20260607     # 指定日
    python export_predictions.py --all        # entries 内の全日付
"""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
from dotenv import load_dotenv

# ── パス設定 ─────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
DB_PATH    = ROOT / "data" / "keiba.db"
MODEL_PATH = ROOT / "data" / "model_placed_pure.lgb"
OUT_DIR    = ROOT / "viewer" / "public" / "predictions"

load_dotenv(ROOT / ".env")

# ── src.api.main から共通ロジックを再利用 ──────────────────────────────────
sys.path.insert(0, str(ROOT))
from src.api.main import (
    _build_features,
    _compute_scores,
    _generate_comment as _generate_comment_tmpl,
    _get_track_type,
    _db,
    VENUE_NAMES,
    FEATURES,
    COMPOSITE_ALPHA,
)

SEX_JP       = {"1": "牡", "2": "牝", "3": "騸", "10": "牡", "20": "牝", "30": "騸"}
MARK_BY_RANK = {0: "◎", 1: "○", 2: "▲", 3: "△", 4: "△", 5: "△", 6: "△"}
MARK_LABELS  = {"◎": "本命", "○": "対抗", "▲": "単穴", "△": "紐"}
MARK_ORDER   = {"◎": 0, "○": 1, "▲": 2, "△": 3}

# ── Claude クライアント ───────────────────────────────────────────────────────
_client_cache = None

def _get_client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    import anthropic
    _client_cache = anthropic.Anthropic(api_key=api_key)
    return _client_cache


def _extract_json(text: str):
    """ClaudeレスポンスからJSONをパースする（複数フォーマット対応）。"""
    for fn in [
        lambda t: json.loads(t.strip()),
        lambda t: json.loads(re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', t).group(1)),
        lambda t: json.loads(re.search(r'(\{[\s\S]*\})', t, re.DOTALL).group(1)),
        lambda t: json.loads(re.search(r'(\[[\s\S]*\])', t, re.DOTALL).group(1)),
    ]:
        try:
            return fn(text)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return None


def _get_track_type_smart(race_name: str | None, condition_text: str | None, venue: str, distance) -> str:
    """race_name / condition_text から surface を判定。不明時は既存ロジックへフォールバック。"""
    text = f"{race_name or ''} {condition_text or ''}"
    if "障害" in text or "スティープル" in text:
        return "障害"
    if "芝" in text:
        return "芝"
    if "ダ" in text:
        return "ダート"
    return _get_track_type(venue, distance)


def _running_style(f: dict) -> str:
    """特徴量から脚質を推定する。"""
    c4 = f.get("horse_avg_corner4", np.nan)
    st = f.get("starters", 10)
    if not (np.isfinite(c4) and np.isfinite(st) and st > 0):
        return "不明"
    r = c4 / st
    return "逃先" if r < 0.3 else ("先行" if r < 0.5 else ("差し" if r < 0.65 else "追込"))


# ── Claude API: レース概況・コース解説（1レースあたり1回） ──────────────────

def _generate_race_overview(
    client,
    venue_name: str,
    race_name: str,
    distance: int,
    track_type: str,
    feats: list,
) -> dict:
    default = {
        "weather": "晴れ",
        "track_condition": "良",
        "track_bias": "バイアス情報なし",
        "pace_prediction": "展開予想なし",
        "lineup": "データなし",
        "course_description": f"{venue_name}競馬場{distance}mの解説なし",
    }
    if client is None:
        return default

    def _pos_str(f: dict) -> str:
        return "・".join(
            str(int(f[f"horse_pos_{k}"])) if np.isfinite(f.get(f"horse_pos_{k}", np.nan)) else "-"
            for k in range(1, 6)
        )

    horse_lines = "\n".join(
        f"{f['horse_num']}番 {f['horse_name']}({_running_style(f)}/{f.get('trainer_name', '')}) "
        f"近走:{_pos_str(f)}"
        for f in feats
    )

    prompt = (
        f"競馬評論家として以下のレースを分析してください。\n"
        f"レース: {venue_name}競馬場 {distance}m {track_type} {race_name}\n"
        f"出走馬:\n{horse_lines}\n\n"
        "以下のJSON形式のみで回答してください（説明文不要）:\n"
        "{\n"
        '  "weather": "晴れ/曇り/雨のいずれか",\n'
        '  "track_condition": "良/稍重/重/不良のいずれか",\n'
        '  "track_bias": "200字程度のトラックバイアス解説",\n'
        '  "pace_prediction": "500字程度の詳細な展開予想",\n'
        '  "lineup": "先頭から順に 馬番:馬名(脚質) の形式で改行区切りの縦リスト",\n'
        f'  "course_description": "{venue_name}競馬場{distance}mの特徴と勝ちやすい馬のタイプを300字程度で"\n'
        "}"
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        r = _extract_json(resp.content[0].text)
        if isinstance(r, dict):
            return {**default, **r}
        print("    警告: レース概況JSON解析失敗")
        print("    Raw:", resp.content[0].text[:300])
    except Exception as e:
        print(f"    Claude API error (overview): {e}")
    return default


# ── Claude API: 全馬スコア・解説（1レースあたり1回） ─────────────────────────

def _generate_horse_ai(
    client,
    venue_name: str,
    race_name: str,
    distance: int,
    track_type: str,
    weather: str,
    track_condition: str,
    feats: list,
) -> list:
    if client is None:
        return []

    def _ag(f: dict, k: int) -> str:
        v = f.get(f"horse_agari_{k}", np.nan)
        return f"{float(v):.1f}" if np.isfinite(v) else "-"

    def _pos(f: dict, k: int) -> str:
        v = f.get(f"horse_pos_{k}", np.nan)
        return str(int(v)) if np.isfinite(v) else "-"

    blocks = []
    for f in feats:
        pp  = " ".join(_pos(f, k) for k in range(1, 6))
        ag  = " ".join(_ag(f, k) for k in range(1, 6))
        tr4 = f.get("tr_4f_last", np.nan)
        tr1 = f.get("tr_1f_last", np.nan)
        tr  = (f"4F:{float(tr4):.1f}" if np.isfinite(tr4) else "なし")
        if np.isfinite(tr1):
            tr += f"/1F:{float(tr1):.1f}"
        sex = SEX_JP.get(str(f.get("_sex_code", "")), "")

        # コース適性情報
        cur_tt  = f.get("_race_track_type", "")
        st_n    = int(f.get("same_track_n_races", 0) or 0)
        st_pr   = f.get("same_track_place_rate", np.nan)
        st_pr_s = f"{st_pr*100:.0f}%" if np.isfinite(st_pr) else "-"
        turf_n  = int(f.get("turf_n_races", 0) or 0)
        dart_n  = int(f.get("dart_n_races", 0) or 0)
        ts      = int(f.get("track_switch", 1) or 1)

        # 同コース直近5走の着順
        st_pp = " ".join(
            str(int(f[f"st_pos_{k}"])) if np.isfinite(f.get(f"st_pos_{k}", np.nan)) else "-"
            for k in range(1, 6)
        )
        st_ag2 = " ".join(
            f"{float(f[f'st_agari_{k}']):.1f}" if np.isfinite(f.get(f"st_agari_{k}", np.nan)) else "-"
            for k in range(1, 6)
        )
        course_info = (
            f"今回コース:{cur_tt} 同コース成績:{st_n}戦{st_pr_s} "
            f"芝:{turf_n}戦 ダート:{dart_n}戦 "
            f"コース替わり:{'あり' if ts else 'なし'}"
        )

        blocks.append(
            f"馬番{f['horse_num']}: {f['horse_name']} {f.get('_horse_age', '')}歳{sex} "
            f"脚質:{_running_style(f)} 枠:{f['gate_num']} "
            f"騎手:{f.get('trainer_name', '')} 調教師:{f.get('jockey_name', '')}\n"
            f"  全コース近走着順: {pp}  上がり3F: {ag}  調教: {tr}\n"
            f"  {cur_tt}近走着順: {st_pp}  {cur_tt}上がり3F: {st_ag2}\n"
            f"  {course_info}"
        )

    prompt = (
        f"競馬評論家として採点・解説してください。\n"
        f"レース: {venue_name}競馬場 {distance}m {track_type} {race_name} "
        f"天気:{weather} 馬場:{track_condition}\n\n"
        + "\n\n".join(blocks) + "\n\n"
        "各10点満点: ability=能力（複勝率・着順）, bloodline=血統（距離・コース適性）, "
        "environment=環境（コース・天気・枠順・展開）, bias=トラックバイアス（脚質×コース傾向）, "
        "keshi=照合（過去好走馬との類似度）, training=調教（タイム・状態）\n\n"
        "以下のJSON配列のみで回答（説明文不要）:\n"
        "[\n"
        '  {"horse_num": "馬番(文字列)", '
        '"scores": {"ability": 点, "bloodline": 点, "environment": 点, '
        '"bias": 点, "keshi": 点, "training": 点}, '
        '"comment": "300字以上（評価点・懸念点・具体的根拠を含む）"},\n'
        "  ...\n"
        "]"
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
        r = _extract_json(resp.content[0].text)
        if isinstance(r, list):
            return r
        print("    警告: 馬採点JSON解析失敗")
        print("    Raw:", resp.content[0].text[:300])
    except Exception as e:
        print(f"    Claude API error (horse AI): {e}")
    return []


# ── 買い目パターン ────────────────────────────────────────────────────────────

def _tickets(top7: list[str]) -> dict:
    """◎○▲△△△△の7頭から4パターンの買い目を生成する。
    馬連A: ◎→○▲ (2点)
    馬連B: ◎or○含む全ペア (11点: C(7,2)-C(5,2)=11)
    3連複A: ◎+{○▲△△△△}から2頭 (15点: C(6,2))
    3連複B: ◎or○含む全3頭組み (25点: C(7,3)-C(5,3)=25)
    """
    empty = {"umaren_a": [], "umaren_b": [], "sanrenpuku_a": [], "sanrenpuku_b": []}
    if len(top7) < 2:
        return empty
    honmei, taikou = top7[0], top7[1]

    umaren_a = [
        {"type": "馬連", "desc": f"馬連 {honmei}-{n}"}
        for n in top7[1:3]
    ]

    umaren_b = [
        {"type": "馬連", "desc": f"馬連 {a}-{b}"}
        for i, a in enumerate(top7) for b in top7[i + 1:]
        if a in (honmei, taikou) or b in (honmei, taikou)
    ]

    rest = top7[1:]
    sanrenpuku_a = [
        {"type": "3連複", "desc": f"3連複 {honmei}-{a}-{b}"}
        for a, b in itertools.combinations(rest, 2)
    ]

    sanrenpuku_b = [
        {"type": "3連複", "desc": f"3連複 {a}-{b}-{c}"}
        for a, b, c in itertools.combinations(top7, 3)
        if a in (honmei, taikou) or b in (honmei, taikou) or c in (honmei, taikou)
    ]

    return {
        "umaren_a": umaren_a,
        "umaren_b": umaren_b,
        "sanrenpuku_a": sanrenpuku_a,
        "sanrenpuku_b": sanrenpuku_b,
    }


# ── レース名補完 ──────────────────────────────────────────────────────────────

def _auto_race_name(
    race_name: str | None,
    grade_code: str | None,
    condition_text: str | None,
    distance: int | None,
    venue_code: str,
) -> str:
    cleaned = " ".join((race_name or "").split())
    gc = (grade_code or "").strip()

    if gc in ("A", "B", "C", "D", "E"):
        return cleaned or f"特別{distance}m"

    if cleaned:
        return cleaned

    dist_str = f"{distance}m" if distance else ""

    tt = _get_track_type_smart(race_name, condition_text, venue_code, distance)
    if tt == "障害" or (distance and distance >= 2500 and tt != "芝"):
        return f"障害{dist_str}"

    ct = (condition_text or "").upper()
    if "MAIDEN" in ct or "SHINJIN" in ct:
        return "新馬"
    if "NOVICE" in ct or "0WIN" in ct:
        return f"{dist_str}未勝利"
    if "1WIN" in ct:
        return f"{dist_str}1勝クラス"
    if "2WIN" in ct:
        return f"{dist_str}2勝クラス"
    if "3WIN" in ct:
        return f"{dist_str}3勝クラス"

    if "新馬" in cleaned:
        return "新馬"
    if "未勝利" in cleaned:
        return f"{dist_str}未勝利"
    for k in ("1勝", "2勝", "3勝"):
        if k in cleaned:
            return f"{dist_str}{k}クラス"
    if "障害" in cleaned:
        return f"障害{dist_str}"

    return f"{dist_str}一般" if dist_str else "一般"


# ── 1レース分の予想を計算 ─────────────────────────────────────────────────────

def _predict_race(
    model: lgb.Booster,
    date: str,
    venue: str,
    race_num: str,
) -> dict | None:
    feats = _build_features(date, venue, race_num)
    if not feats:
        return None

    X     = np.array([[f[col] for col in FEATURES] for f in feats], dtype=float)
    probs = model.predict(X)

    # 全馬スコアを先に計算（複合スコアで印を決めるため）
    all_scores_base = [_compute_scores(f) for f in feats]
    all_totals_base = [sum(s.values()) for s in all_scores_base]
    composite = np.array([
        float(probs[i]) * (all_totals_base[i] / 60.0) ** COMPOSITE_ALPHA
        for i in range(len(feats))
    ])
    order   = np.argsort(-composite)
    rank_of = {int(idx): int(pos) for pos, idx in enumerate(order)}

    with _db() as db:
        meta = db.execute("""
            SELECT MAX(race_name) race_name, MAX(distance) distance,
                   MAX(grade_code) grade_code, MAX(condition_text) condition_text,
                   MAX(day_num) day_num
            FROM entries WHERE race_date=? AND venue_code=? AND race_num=?
        """, (date, venue, race_num)).fetchone()

    if not meta:
        return None

    # entries.track_typeが取得済みならそれを使う（RA2 byte705由来、最も正確）
    _feat_tt = feats[0].get("_race_track_type") if feats else None
    tt = _feat_tt or _get_track_type_smart(meta["race_name"], meta["condition_text"], venue, meta["distance"])
    race_name  = _auto_race_name(
        meta["race_name"], meta["grade_code"], meta["condition_text"], meta["distance"], venue
    )
    venue_name = VENUE_NAMES.get(venue, venue)
    client     = _get_client()

    # Claude API 呼び出し 1: レース概況・コース解説
    print(f"    AI[1/2] レース概況生成中...")
    overview = _generate_race_overview(
        client, venue_name, race_name, meta["distance"] or 0, tt, feats
    )

    # Claude API 呼び出し 2: 全馬スコア・解説
    print(f"    AI[2/2] {len(feats)}頭スコア・解説生成中...")
    horse_ai_list = _generate_horse_ai(
        client, venue_name, race_name, meta["distance"] or 0, tt,
        overview["weather"], overview["track_condition"], feats,
    )
    horse_ai_map = {str(h.get("horse_num", "")): h for h in horse_ai_list}

    horses = []
    for i, f in enumerate(feats):
        model_rank = rank_of[i]
        prob_pct   = round(float(probs[i]) * 100, 1)

        ai = horse_ai_map.get(str(f["horse_num"]), {})
        if ai and "scores" in ai:
            raw = ai["scores"]
            scores = {
                k: max(0, min(10, int(raw.get(k, 5) or 5)))
                for k in ("ability", "bloodline", "environment", "bias", "keshi", "training")
            }
        else:
            scores = _compute_scores(f)

        comment = (ai.get("comment") or "") if ai else ""
        if not comment:
            comment = _generate_comment_tmpl(f, scores, tt)

        horses.append({
            "model_rank":   model_rank + 1,
            "horse_num":    f["horse_num"],
            "gate_num":     f["gate_num"],
            "horse_name":   f["horse_name"],
            "jockey_name":  f["trainer_name"],   # DB格納順が逆のため
            "trainer_name": f["jockey_name"],
            "sex":          SEX_JP.get(f.get("_sex_code", ""), ""),
            "horse_age":    f.get("_horse_age", ""),
            "mark":         MARK_BY_RANK.get(model_rank, ""),
            "prob":         prob_pct,
            "scores":       scores,
            "total_score":  sum(scores.values()),
            "comment":      comment,
            "past_5": [
                {
                    "pos":   int(f[f"horse_pos_{k}"])
                              if np.isfinite(f[f"horse_pos_{k}"]) else None,
                    "agari": round(float(f[f"horse_agari_{k}"]), 1)
                              if np.isfinite(f[f"horse_agari_{k}"]) else None,
                }
                for k in range(1, 6)
            ],
        })

    top7    = [horses[i]["horse_num"] for i in order[:min(7, len(order))]]
    tickets = _tickets(top7)

    marks = sorted(
        [
            {
                "mark":       h["mark"],
                "label":      MARK_LABELS.get(h["mark"], ""),
                "horse_num":  h["horse_num"],
                "horse_name": h["horse_name"],
                "prob":       h["prob"],
            }
            for h in horses if h["mark"] in MARK_LABELS
        ],
        key=lambda x: MARK_ORDER.get(x["mark"], 9),
    )

    return {
        "race_num":    race_num.lstrip("0") or race_num,
        "race_name":   race_name,
        "distance":    meta["distance"],
        "track_type":  tt,
        "grade_code":  (meta["grade_code"] or "").strip(),
        "starters":    len(feats),
        "caution": {
            "weather":         overview["weather"],
            "track_condition": overview["track_condition"],
            "track_bias":      overview["track_bias"],
            "pace_prediction": overview["pace_prediction"],
            "lineup":          overview["lineup"],
        },
        "course_description": overview["course_description"],
        "horses":    horses,
        "recommendations": {
            "marks":   marks,
            "tickets": tickets,
        },
    }


# ── 1日分のデータを生成 ───────────────────────────────────────────────────────

def _build_date(model: lgb.Booster, date: str) -> dict:
    with _db() as db:
        venue_rows = db.execute("""
            SELECT venue_code FROM entries WHERE race_date = ?
            GROUP BY venue_code ORDER BY venue_code
        """, (date,)).fetchall()

    venues = []
    for vrow in venue_rows:
        venue_code = vrow[0]
        venue_name = VENUE_NAMES.get(venue_code, venue_code)

        with _db() as db:
            race_rows = db.execute("""
                SELECT race_num FROM entries WHERE race_date = ? AND venue_code = ?
                GROUP BY race_num ORDER BY CAST(race_num AS INTEGER)
            """, (date, venue_code)).fetchall()

        races = []
        for rrow in race_rows:
            race_num = rrow[0]
            result = _predict_race(model, date, venue_code, race_num)
            if result:
                races.append(result)

        if races:
            venues.append({"venue_code": venue_code, "venue_name": venue_name, "races": races})

    return {"venues": venues}


# ── JSON シリアライズ ─────────────────────────────────────────────────────────

class _NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):  return int(o)
        if isinstance(o, np.floating): return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):  return o.tolist()
        return super().default(o)


# ── エントリーポイント ────────────────────────────────────────────────────────

def main():
    with _db() as db:
        all_dates = [
            r[0] for r in db.execute(
                "SELECT DISTINCT race_date FROM entries ORDER BY race_date DESC"
            ).fetchall()
        ]

    if not all_dates:
        print("entries テーブルにデータがありません。")
        return

    if "--all" in sys.argv:
        target_dates = list(reversed(all_dates))
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        target_dates = [sys.argv[1]]
    else:
        target_dates = [all_dates[0]]

    if not MODEL_PATH.exists():
        print(f"ERROR: モデルが見つかりません: {MODEL_PATH}")
        return
    model = lgb.Booster(model_file=str(MODEL_PATH))
    print(f"モデルロード完了: {model.num_trees()} trees, {model.num_feature()} features")
    print(f"Claude API: {'接続済み' if _get_client() else '未設定（テンプレート生成にフォールバック）'}")

    OUT_DIR.mkdir(exist_ok=True)
    generated_at  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first_race_kv = None  # (venue_name, race_dict) for test output

    for date in target_dates:
        print(f"\n--- {date} 処理中 ---")
        date_data = _build_date(model, date)

        payload = {
            "generated_at": generated_at,
            "dates": [date],
            date: date_data,
        }

        out_path = OUT_DIR / f"{date}.json"
        out_path.write_text(
            json.dumps(payload, cls=_NpEncoder, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  保存: {out_path}  ({out_path.stat().st_size / 1024:.1f} KB)")

        total_races = 0
        for v in date_data["venues"]:
            for r in v["races"]:
                total_races += 1
                print(
                    f"  {v['venue_name']} {r['race_num']}R "
                    f"{r['race_name']:20s}  "
                    f"{r['distance']}m {r['track_type']:2s}  "
                    f"{r['starters']}頭"
                )
                if first_race_kv is None:
                    first_race_kv = (v["venue_name"], r)
        print(f"  合計: {total_races} レース")

    # ── テスト出力（注意書き・展開予想・隊列図・コース解説・1頭スコア） ──
    if first_race_kv:
        vname, r = first_race_kv
        sep = "=" * 64
        print(f"\n{sep}")
        print(f"【テスト出力】{vname} {r['race_num']}R {r['race_name']} {r['distance']}m {r['track_type']}")
        c = r.get("caution", {})
        print(f"\n【天候想定】{c.get('weather', '-')}")
        print(f"【芝状態想定】{c.get('track_condition', '-')}")
        print(f"\n【トラックバイアス想定】\n{c.get('track_bias', '-')}")
        print(f"\n【展開予想】\n{c.get('pace_prediction', '-')}")
        print(f"\n【隊列図】\n{c.get('lineup', '-')}")
        print(f"\n【コース・距離解説】\n{r.get('course_description', '-')}")

        if r.get("horses"):
            h = sorted(r["horses"], key=lambda x: x["model_rank"])[0]
            s = h["scores"]
            print(f"\n{sep}")
            print(f"【注目馬: {h['horse_name']}（{h['mark']}）】")
            print(
                f"スコア: 能力{s['ability']} 血統{s['bloodline']} 環境{s['environment']} "
                f"バイアス{s['bias']} 照合{s['keshi']} 調教{s['training']} "
                f"= {h['total_score']}点/60点中"
            )
            print(f"\n【解説】\n{h['comment']}")
        print(sep)

    # manifest.json 更新（8桁数字ファイルのみ、manifest自身を除外）
    all_json_dates = sorted(
        p.stem for p in OUT_DIR.glob("????????.json")
        if p.stem.isdigit()
    )
    (OUT_DIR / "manifest.json").write_text(
        json.dumps({"dates": all_json_dates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nmanifest.json 更新: {all_json_dates}")


if __name__ == "__main__":
    main()
