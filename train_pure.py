"""
popularity のみを除外した複勝予測モデル。
騎手・調教師成績は残し、「オッズ情報なし」で予測する。

キャッシュ: data/features_cache.pkl  (なければ構築して保存)
モデル出力: data/model_placed_pure.lgb
"""
import sys, time, pickle
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")

from src.model.trainer import (
    load_results, add_horse_features, add_race_features,
    add_jockey_features, add_trainer_features, add_training_features,
    DB_PATH, LGB_PARAMS,
    TRAIN_START, TRAIN_END, VAL_START, VAL_END,
    FEATURE_COLS as FEAT_ALL,          # 39個（popularity含む）
)

RACE_KEY    = ["race_date", "venue_code", "meeting_num", "day_num", "race_num"]
CACHE_PATH  = DB_PATH.parent / "features_cache.pkl"
MODEL_PURE  = DB_PATH.parent / "model_placed_pure.lgb"
MODEL_ODDS  = DB_PATH.parent / "model_placed.lgb"

# popularity だけ除いた 38 特徴量
FEAT_PURE = [f for f in FEAT_ALL if f != "popularity"]


# ── 特徴量: キャッシュ or 新規構築 ───────────────────────────────────────────

def build_or_load() -> pd.DataFrame:
    if CACHE_PATH.exists():
        t = time.time()
        print(f"キャッシュ読み込み: {CACHE_PATH}")
        df = pd.read_pickle(CACHE_PATH)
        print(f"  {len(df):,}行  ({time.time()-t:.1f}s)")
        return df

    print("特徴量を新規構築します（約7分）…")
    t0 = time.time()

    all_r = load_results()
    print(f"  [{time.time()-t0:.0f}s] {len(all_r):,}行 読み込み完了")

    all_r = add_horse_features(all_r)
    print(f"  [{time.time()-t0:.0f}s] 馬能力特徴量")

    all_r = add_race_features(all_r)

    tgt = all_r[all_r["race_date"] >= TRAIN_START].copy()
    tgt = add_jockey_features(tgt, all_r)
    print(f"  [{time.time()-t0:.0f}s] 騎手特徴量")

    tgt = add_trainer_features(tgt, all_r)
    print(f"  [{time.time()-t0:.0f}s] 調教師特徴量")

    tgt = add_training_features(tgt)
    print(f"  [{time.time()-t0:.0f}s] 調教タイム特徴量")

    pd.to_pickle(tgt, CACHE_PATH)
    print(f"  キャッシュ保存: {CACHE_PATH}")
    return tgt


# ── 評価 ─────────────────────────────────────────────────────────────────────

def evaluate(model: lgb.Booster, df: pd.DataFrame, feat: list[str], label: str):
    prob = model.predict(df[feat])
    auc  = roc_auc_score(df["is_placed"], prob)

    tmp        = df[RACE_KEY + ["is_placed"]].copy()
    tmp["prob"] = prob

    hit1 = (
        tmp.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False).head(1)
        ["is_placed"].mean()
    )
    hit3 = (
        tmp.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False).head(3)
        .groupby(RACE_KEY)["is_placed"].max().mean()
    )
    base = df["is_placed"].mean()

    print(f"  {label}")
    print(f"    AUC              : {auc:.4f}")
    print(f"    複勝率(全体)     : {base:.1%}")
    print(f"    予測1位馬 複勝率 : {hit1:.1%}  (lift {hit1/base:.2f}x)")
    print(f"    上位3頭 いずれか : {hit3:.1%}")
    return auc, hit1, hit3


# ── 特徴量重要度 ─────────────────────────────────────────────────────────────

def show_importance(model: lgb.Booster, top_n: int = 10):
    imp = pd.DataFrame({
        "feature": model.feature_name(),
        "gain":    model.feature_importance("gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    mx = imp["gain"].max()
    print(f"\n=== 特徴量重要度 TOP {top_n} (gain) ===")
    for _, r in imp.head(top_n).iterrows():
        bar = "█" * max(1, int(r["gain"] / mx * 30))
        print(f"  {r['feature']:<30} {r['gain']:>10,.0f}  {bar}")
    return imp


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()

    # 1. 特徴量
    target   = build_or_load()
    train_df = target[target["race_date"] <= TRAIN_END].copy()
    val_df   = target[(target["race_date"] >= VAL_START)
                      & (target["race_date"] <= VAL_END)].copy()

    print(f"\n学習: {len(train_df):,}行  検証: {len(val_df):,}行")
    print(f"使用特徴量: {len(FEAT_PURE)}個  (除外: popularity)\n")

    # 2. 学習
    print("=== LightGBM 学習 ===")
    dtrain = lgb.Dataset(train_df[FEAT_PURE], label=train_df["is_placed"],
                         feature_name=FEAT_PURE)
    dval   = lgb.Dataset(val_df[FEAT_PURE],   label=val_df["is_placed"],
                         reference=dtrain)

    model = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=3000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(100, verbose=True),
            lgb.log_evaluation(200),
        ],
    )

    # 3. 評価
    print(f"\n{'='*55}")
    print("  検証データ評価 (2024-2025)")
    print(f"{'='*55}")
    auc_p, h1_p, h3_p = evaluate(model, val_df, FEAT_PURE, "popularity除外モデル (38特徴量)")

    if MODEL_ODDS.exists():
        print()
        model_o = lgb.Booster(model_file=str(MODEL_ODDS))
        auc_o, h1_o, h3_o = evaluate(model_o, val_df, FEAT_ALL, "オリジナルモデル  (39特徴量)")
        print(f"\n  ── 差分 (popularity除外 − オリジナル) ──")
        print(f"    AUC    : {auc_p-auc_o:+.4f}  ({auc_p:.4f} vs {auc_o:.4f})")
        print(f"    複勝率 : {h1_p-h1_o:+.1%}   ({h1_p:.1%} vs {h1_o:.1%})")

    # 4. 特徴量重要度
    show_importance(model)

    # 5. 保存
    model.save_model(str(MODEL_PURE))
    print(f"\nモデル保存: {MODEL_PURE}")
    print(f"総処理時間: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
