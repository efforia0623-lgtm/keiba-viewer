"""
予想結果を JSON ファイルに出力するスクリプト。

Usage:
    python export_predictions.py              # 最新日付（entries の最大日）
    python export_predictions.py 20260607     # 指定日
    python export_predictions.py --all        # entries 内の全日付
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
from dotenv import load_dotenv

# ── パス設定 ─────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
load_dotenv(ROOT / ".env")
DB_PATH     = ROOT / "data" / "keiba.db"
MODEL_PATH  = ROOT / "data" / "model_placed_pure.lgb"
OUT_DIR     = ROOT / "viewer" / "public" / "predictions"

# ── src.api.main から共通ロジックを再利用 ──────────────────────────────────
sys.path.insert(0, str(ROOT))
from src.api.main import (
    _build_features,
    _compute_scores,
    _generate_comment,
    _get_track_type,
    _tickets,
    _db,
    VENUE_NAMES,
    FEATURES,
)

SEX_JP = {"1": "牡", "2": "牝", "3": "騸", "10": "牡", "20": "牝", "30": "騸"}
MARK_BY_RANK  = {0: "◎", 1: "○", 2: "▲", 3: "△", 4: "△", 5: "△"}
MARK_LABELS   = {"◎": "本命", "○": "対抗", "▲": "単穴"}

_anthropic_client = None

def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    import anthropic
    _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def _generate_comment(f: dict, scores: dict, track_type: str) -> str:
    """Claude APIで解説文を生成する。APIキー未設定時はテンプレート生成にフォールバック。"""
    from src.api.main import _generate_comment as _tmpl

    client = _get_anthropic_client()
    if client is None:
        return _tmpl(f, scores, track_type)

    horse_name = f.get("horse_name", "不明")
    horse_age  = f.get("_horse_age", "")
    sex        = SEX_JP.get(str(f.get("_sex_code", "")), "")
    # DBではjockey/trainerが逆格納
    jockey     = f.get("trainer_name", "")
    trainer    = f.get("jockey_name", "")
    distance   = int(f["distance"]) if np.isfinite(f.get("distance", np.nan)) else 0

    past_pos   = []
    past_agari = []
    for k in range(1, 6):
        pos = f.get(f"horse_pos_{k}", np.nan)
        past_pos.append(str(int(pos)) if np.isfinite(pos) else "-")
        agari = f.get(f"horse_agari_{k}", np.nan)
        past_agari.append(f"{float(agari):.1f}" if np.isfinite(agari) else "-")

    score_text = "、".join(f"{k}:{v}" for k, v in scores.items())
    prompt = (
        f"競馬評論家として{horse_name}の解説を300字程度で。"
        f"近走成績の分析、今回のレース条件への適性、脚質と展開の合致、懸念点を具体的な根拠とともに書いてください。\n\n"
        f"馬名：{horse_name}\n"
        f"年齢・性別：{horse_age}歳{sex}\n"
        f"過去5走着順：{', '.join(past_pos)}\n"
        f"上がり3F：{', '.join(past_agari)}\n"
        f"騎手：{jockey}\n"
        f"調教師：{trainer}\n"
        f"距離：{distance}m\n"
        f"コース：{track_type}\n"
        f"6項目スコア（能力/血統/環境/展開/過去/調教）：{score_text}"
    )

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"  Claude API error ({horse_name}): {e}")
        return _tmpl(f, scores, track_type)


# ── レース名補完 ──────────────────────────────────────────────────────────────

def _auto_race_name(
    race_name: str | None,
    grade_code: str | None,
    condition_text: str | None,
    distance: int | None,
    venue_code: str,
) -> str:
    """race_name が空の場合にgrade_code・condition_text・距離から補完する。"""
    # SJIS→str 変換で残る連続スペースを単一スペースに圧縮
    cleaned = " ".join((race_name or "").split())
    gc = (grade_code or "").strip()

    # 特別競走・重賞はレース名をそのまま使用
    if gc in ("A", "B", "C", "D", "E"):
        return cleaned or f"特別{distance}m"

    # 以下 grade=' '（一般レース）の補完
    if cleaned:
        return cleaned  # race_name があればそのまま

    dist_str = f"{distance}m" if distance else ""

    # 障害: track_type 判定
    tt = _get_track_type(venue_code, distance)
    if tt == "障害" or (distance and distance >= 2500 and tt != "芝"):
        return f"障害{dist_str}"

    # condition_text キーワード判定（ES_DATA 経由でロードした場合に有効）
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

    # 日本語キーワード（race_name に断片が入る場合）
    if "新馬" in cleaned:
        return "新馬"
    if "未勝利" in cleaned:
        return f"{dist_str}未勝利"
    for k in ("1勝", "2勝", "3勝"):
        if k in cleaned:
            return f"{dist_str}{k}クラス"
    if "障害" in cleaned:
        return f"障害{dist_str}"

    # 最終フォールバック: 距離のみ
    return f"{dist_str}一般" if dist_str else "一般"


# ── 1レース分の予想を計算 ─────────────────────────────────────────────────

def _predict_race(
    model: lgb.Booster,
    date: str,
    venue: str,
    race_num: str,
) -> dict | None:
    """1レース分の予想辞書を返す。エラー時は None。"""
    feats = _build_features(date, venue, race_num)
    if not feats:
        return None

    X     = np.array([[f[col] for col in FEATURES] for f in feats], dtype=float)
    probs = model.predict(X)
    order = np.argsort(-probs)
    rank_of = {int(idx): int(pos) for pos, idx in enumerate(order)}

    # メタ情報（entries から）
    with _db() as db:
        meta = db.execute("""
            SELECT MAX(race_name) race_name, MAX(distance) distance,
                   MAX(grade_code) grade_code, MAX(condition_text) condition_text,
                   MAX(day_num) day_num
            FROM entries WHERE race_date=? AND venue_code=? AND race_num=?
        """, (date, venue, race_num)).fetchone()

    if not meta:
        return None

    tt = _get_track_type(venue, meta["distance"])
    race_name = _auto_race_name(
        meta["race_name"], meta["grade_code"],
        meta["condition_text"], meta["distance"], venue,
    )

    horses = []
    for i, f in enumerate(feats):
        model_rank = rank_of[i]
        prob_pct   = round(float(probs[i]) * 100, 1)
        scores     = _compute_scores(f)
        comment    = _generate_comment(f, scores, tt)
        horses.append({
            "model_rank":  model_rank + 1,
            "horse_num":   f["horse_num"],
            "gate_num":    f["gate_num"],
            "horse_name":  f["horse_name"],
            "jockey_name": f["trainer_name"],   # DB格納順が逆のため
            "trainer_name": f["jockey_name"],
            "sex":         SEX_JP.get(f.get("_sex_code", ""), ""),
            "horse_age":   f.get("_horse_age", ""),
            "mark":        MARK_BY_RANK.get(model_rank, ""),
            "prob":        prob_pct,
            "scores":      scores,
            "total_score": sum(scores.values()),
            "comment":     comment,
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

    top3    = [horses[i]["horse_num"] for i in order[:3]]
    tickets = _tickets(top3)

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
        key=lambda x: x["prob"],
        reverse=True,
    )
    himo = sorted(
        [
            {"horse_num": h["horse_num"], "horse_name": h["horse_name"], "prob": h["prob"]}
            for h in horses if h["mark"] == "△"
        ],
        key=lambda x: x["prob"],
        reverse=True,
    )

    return {
        "race_num":   race_num.lstrip("0") or race_num,
        "race_name":  race_name,
        "distance":   meta["distance"],
        "track_type": tt,
        "grade_code": (meta["grade_code"] or "").strip(),
        "starters":   len(feats),
        "horses":     horses,
        "recommendations": {
            "marks":  marks,
            "himo":   himo,
            "tickets": tickets,
        },
        "tickets": tickets,
    }


# ── 1日分のデータを生成 ───────────────────────────────────────────────────────

def _build_date(model: lgb.Booster, date: str) -> dict:
    """date の全会場・全レースを予想して辞書で返す。"""
    with _db() as db:
        venue_rows = db.execute("""
            SELECT venue_code
            FROM entries WHERE race_date = ?
            GROUP BY venue_code ORDER BY venue_code
        """, (date,)).fetchall()

    venues = []
    for vrow in venue_rows:
        venue_code = vrow[0]
        venue_name = VENUE_NAMES.get(venue_code, venue_code)

        with _db() as db:
            race_rows = db.execute("""
                SELECT race_num
                FROM entries WHERE race_date = ? AND venue_code = ?
                GROUP BY race_num ORDER BY CAST(race_num AS INTEGER)
            """, (date, venue_code)).fetchall()

        races = []
        for rrow in race_rows:
            race_num = rrow[0]
            result = _predict_race(model, date, venue_code, race_num)
            if result:
                races.append(result)

        if races:
            venues.append({
                "venue_code": venue_code,
                "venue_name": venue_name,
                "races":      races,
            })

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
    # 対象日付を決定
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
        target_dates = [all_dates[0]]  # 最新日

    # モデルロード
    if not MODEL_PATH.exists():
        print(f"ERROR: モデルが見つかりません: {MODEL_PATH}")
        return
    model = lgb.Booster(model_file=str(MODEL_PATH))
    print(f"モデルロード完了: {model.num_trees()} trees, {model.num_feature()} features")

    # 出力フォルダ作成
    OUT_DIR.mkdir(exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for date in target_dates:
        print(f"\n--- {date} 処理中 ---")
        date_data = _build_date(model, date)

        payload = {
            "generated_at": generated_at,
            "dates":        [date],
            date:           date_data,
        }

        out_path = OUT_DIR / f"{date}.json"
        out_path.write_text(
            json.dumps(payload, cls=_NpEncoder, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        size_kb = out_path.stat().st_size / 1024
        print(f"  保存: {out_path}  ({size_kb:.1f} KB)")

        # レース名一覧を表示
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
        print(f"  合計: {total_races} レース")

    # manifest.json を更新（全 YYYYMMDD.json を列挙）
    all_json_dates = sorted(
        p.stem for p in OUT_DIR.glob("????????.json")
    )
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"dates": all_json_dates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nmanifest.json 更新: {all_json_dates}")


if __name__ == "__main__":
    main()
