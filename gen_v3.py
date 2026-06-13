"""
v3.json 生成スクリプト (Claude API不要・高速版)
複合スコア = prob × (total_score/60)^COMPOSITE_ALPHA で印を決める

Usage:
    python gen_v3.py 20260606
    python gen_v3.py 20260607
"""
import io, json, sys
import numpy as np
import lightgbm as lgb
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.api.main import (
    _build_features, _compute_scores,
    _db, VENUE_NAMES, FEATURES, COMPOSITE_ALPHA,
)

MODEL_PATH = ROOT / "data" / "model_placed_pure.lgb"
OUT_DIR    = ROOT / "viewer" / "public" / "predictions"

SEX_JP       = {"1": "牡", "2": "牝", "3": "騸", "10": "牡", "20": "牝", "30": "騸"}
MARK_BY_RANK = {0: "◎", 1: "○", 2: "▲", 3: "△", 4: "△", 5: "△"}


class _NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):  return int(o)
        if isinstance(o, np.floating): return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):  return o.tolist()
        return super().default(o)


def predict_date(model: lgb.Booster, date: str) -> dict:
    with _db() as db:
        venue_rows = db.execute(
            "SELECT DISTINCT venue_code FROM entries WHERE race_date=? ORDER BY venue_code",
            (date,)
        ).fetchall()

    venues = []
    for vrow in venue_rows:
        vc = vrow[0]
        with _db() as db:
            race_rows = db.execute(
                "SELECT DISTINCT race_num FROM entries WHERE race_date=? AND venue_code=? "
                "ORDER BY CAST(race_num AS INTEGER)",
                (date, vc)
            ).fetchall()

        races = []
        for rrow in race_rows:
            rn = rrow[0]
            feats = _build_features(date, vc, rn)
            if not feats:
                print(f"  {vc}-{rn}R SKIP (no entries)")
                continue

            try:
                X      = np.array([[f[col] for col in FEATURES] for f in feats], dtype=float)
                probs  = model.predict(X)

                all_scores = [_compute_scores(f) for f in feats]
                all_totals = [sum(s.values()) for s in all_scores]

                composite = np.array([
                    float(probs[i]) * (all_totals[i] / 60.0) ** COMPOSITE_ALPHA
                    for i in range(len(feats))
                ])
                order   = np.argsort(-composite)
                rank_of = {int(idx): int(pos) for pos, idx in enumerate(order)}

                horses = []
                for i, f in enumerate(feats):
                    model_rank  = rank_of[i]
                    prob_pct    = round(float(probs[i]) * 100, 1)
                    scores      = all_scores[i]
                    total_score = all_totals[i]
                    composite_score = round(float(composite[i]) * 100, 3)
                    horses.append({
                        "horse_num":        f["horse_num"],
                        "horse_name":       f["horse_name"],
                        "prob":             prob_pct,
                        "composite_score":  composite_score,
                        "model_rank":       model_rank + 1,
                        "mark":             MARK_BY_RANK.get(model_rank, ""),
                        "scores":           scores,
                        "total_score":      total_score,
                    })

                races.append({"race_num": rn, "horses": horses})
                hn = VENUE_NAMES.get(vc, vc)
                top = next((h["horse_name"] for h in horses if h["mark"] == "◎"), "?")
                print(f"  {hn}{rn}R OK  ◎{top}")

            except Exception as e:
                print(f"  {vc}-{rn}R ERROR: {e}")

        if races:
            venues.append({"venue_code": vc, "venue_name": VENUE_NAMES.get(vc, vc), "races": races})

    return {"venues": venues}


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if not date:
        print("Usage: python gen_v3.py YYYYMMDD")
        sys.exit(1)

    print(f"モデルロード中: {MODEL_PATH}")
    model = lgb.Booster(model_file=str(MODEL_PATH))
    print(f"  {model.num_trees()} trees / COMPOSITE_ALPHA={COMPOSITE_ALPHA}")

    print(f"\n--- {date} 生成中 ---")
    data = predict_date(model, date)

    out = OUT_DIR / f"{date}_v3.json"
    out.write_text(
        json.dumps({date: data}, cls=_NpEncoder, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
