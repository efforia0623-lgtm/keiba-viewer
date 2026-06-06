"""
LightGBM オッズなし複勝予測モデル

除外する特徴量:
  - popularity       (人気 = オッズの代理変数)
  - jockey_win*/place*/rides*  (騎手成績 = 市場に織り込み済み)
  - trainer_win*               (調教師成績 = 同上)

純粋に「馬の能力・調教・レース環境」だけで予測する。
オッズを知らずに儲かる予測ができるか検証するモデル。

再実行時はキャッシュ (data/features_cache.pkl) を使い高速化。
"""

import sys, time, pickle
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")

# ── trainer.py から共通関数・定数をインポート ────────────────────────────────
from src.model.trainer import (
    load_results,
    add_horse_features,
    add_race_features,
    add_jockey_features,
    add_trainer_features,
    add_training_features,
    DB_PATH, LGB_PARAMS,
    TRAIN_START, TRAIN_END,
    VAL_START,   VAL_END,
    FEATURE_COLS as FEATURE_COLS_WITH_ODDS,
)

RACE_KEY           = ["race_date", "venue_code", "meeting_num", "day_num", "race_num"]
MODEL_PATH_NO_ODDS = DB_PATH.parent / "model_placed_no_odds.lgb"
MODEL_PATH_ODDS    = DB_PATH.parent / "model_placed.lgb"
CACHE_PATH         = DB_PATH.parent / "features_cache.pkl"

# ── オッズ関連を除外した特徴量リスト (32個) ─────────────────────────────────
FEATURE_COLS_NO_ODDS: list[str] = [
    # 馬能力: 過去5走着順
    *[f"horse_pos_{k}"   for k in range(1, 6)],
    # 馬能力: 過去5走上がり3F
    *[f"horse_agari_{k}" for k in range(1, 6)],
    # 過去5走集計
    "horse_avg_pos_5",
    "horse_win_rate_5",
    "horse_place_rate_5",
    "horse_avg_agari_5",
    # キャリア・脚質・同会場成績
    "horse_n_races",
    "horse_days_last_race",
    "horse_avg_corner4",
    "horse_venue_avg_pos",
    "horse_venue_win_rate",
    "horse_venue_races",
    # レース環境 (popularity は除外)
    "gate_num_int",
    "horse_num_int",
    "starters",
    # 馬体情報
    "horse_age_int",
    "sex_enc",
    "horse_weight",
    "weight_change_int",
    # 調教タイム
    "tr_days_before",
    "tr_4f_last",
    "tr_1f_last",
    "tr_4f_avg14d",
    "tr_sessions_14d",
]

# 除外した特徴量
EXCLUDED = sorted(set(FEATURE_COLS_WITH_ODDS) - set(FEATURE_COLS_NO_ODDS))


# ── 特徴量ビルド（キャッシュあれば再利用） ───────────────────────────────────

def build_or_load_features() -> pd.DataFrame:
    if CACHE_PATH.exists():
        print(f"キャッシュ読み込み中: {CACHE_PATH}")
        t = time.time()
        df = pd.read_pickle(CACHE_PATH)
        print(f"  完了 ({time.time()-t:.1f}s, {len(df):,}行)")
        return df

    print("特徴量を新規構築します (約7〜8分)…")
    t0 = time.time()
    _t = lambda msg: print(f"  [{time.time()-t0:>5.0f}s] {msg}")

    _t("horse_results 読み込み…")
    all_results = load_results()
    _t(f"  {len(all_results):,}行")

    _t("馬能力特徴量…")
    all_results = add_horse_features(all_results)

    _t("レース特徴量…")
    all_results = add_race_features(all_results)

    target = all_results[all_results["race_date"] >= TRAIN_START].copy()

    _t(f"騎手特徴量 ({len(target):,}行)…")
    target = add_jockey_features(target, all_results)

    _t("調教師特徴量…")
    target = add_trainer_features(target, all_results)

    _t("調教タイム特徴量…")
    target = add_training_features(target)

    _t("キャッシュ保存中…")
    pd.to_pickle(target, CACHE_PATH)
    _t(f"保存完了: {CACHE_PATH}")

    return target


# ── 評価関数 ─────────────────────────────────────────────────────────────────

def evaluate_model(
    model: lgb.Booster,
    df: pd.DataFrame,
    feature_cols: list[str],
) -> tuple[float, float, float]:
    """AUC, 予測1位馬複勝率, 上位3頭的中率 を返す。"""
    prob     = model.predict(df[feature_cols])
    auc      = roc_auc_score(df["is_placed"], prob)
    baseline = df["is_placed"].mean()

    df2         = df[RACE_KEY + ["is_placed"]].copy()
    df2["prob"] = prob

    top1 = (
        df2.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False)
        .head(1)
    )
    hit1 = top1["is_placed"].mean()

    top3 = (
        df2.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False)
        .head(3)
    )
    hit3 = top3.groupby(RACE_KEY)["is_placed"].max().mean()

    return auc, hit1, hit3


def print_eval(label: str, auc: float, hit1: float, hit3: float, baseline: float):
    print(f"  {label:<22}  AUC={auc:.4f}  "
          f"予測1位複勝率={hit1:.1%}(lift {hit1/baseline:.2f}x)  "
          f"上位3頭的中={hit3:.1%}")


# ── 特徴量重要度 ─────────────────────────────────────────────────────────────

def show_importance(model: lgb.Booster, top_n: int = 10):
    imp = pd.DataFrame({
        "feature": model.feature_name(),
        "gain":    model.feature_importance(importance_type="gain"),
        "split":   model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    max_gain = imp["gain"].max()
    print(f"\n=== 特徴量重要度 TOP {top_n} (gain)  [オッズなしモデル] ===")
    for _, row in imp.head(top_n).iterrows():
        bar = "█" * max(1, int(row["gain"] / max_gain * 30))
        print(f"  {row['feature']:<30} {row['gain']:>10,.0f}  {bar}")
    return imp


# ── メイン ───────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()

    # 1. 特徴量
    target   = build_or_load_features()
    train_df = target[target["race_date"] <= TRAIN_END].copy()
    val_df   = target[
        (target["race_date"] >= VAL_START) & (target["race_date"] <= VAL_END)
    ].copy()

    print(f"\n学習: {len(train_df):,}行  検証: {len(val_df):,}行")
    print(f"除外特徴量 ({len(EXCLUDED)}個): {', '.join(EXCLUDED)}")
    print(f"使用特徴量 ({len(FEATURE_COLS_NO_ODDS)}個)\n")

    # 2. LightGBM 学習（オッズなし）
    print("=== LightGBM 学習 (オッズなし) ===")
    dtrain = lgb.Dataset(
        train_df[FEATURE_COLS_NO_ODDS], label=train_df["is_placed"],
        feature_name=FEATURE_COLS_NO_ODDS,
    )
    dval = lgb.Dataset(
        val_df[FEATURE_COLS_NO_ODDS], label=val_df["is_placed"],
        reference=dtrain,
    )

    model_no_odds = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=3000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=100, verbose=True),
            lgb.log_evaluation(period=200),
        ],
    )

    # 3. 精度比較（検証データ）
    baseline = val_df["is_placed"].mean()
    print(f"\n{'='*70}")
    print(f"  モデル比較  (検証データ 2024-2025  is_placed率={baseline:.1%})")
    print(f"{'='*70}")

    auc_n, hit1_n, hit3_n = evaluate_model(model_no_odds, val_df, FEATURE_COLS_NO_ODDS)
    print_eval("オッズなし (32特徴量)", auc_n, hit1_n, hit3_n, baseline)

    if MODEL_PATH_ODDS.exists():
        model_odds = lgb.Booster(model_file=str(MODEL_PATH_ODDS))
        auc_o, hit1_o, hit3_o = evaluate_model(model_odds, val_df, FEATURE_COLS_WITH_ODDS)
        print_eval("オッズあり (39特徴量)", auc_o, hit1_o, hit3_o, baseline)

        print(f"\n  差分 (オッズなし − あり):")
        print(f"    AUC    : {auc_n - auc_o:+.4f}  ({auc_n:.4f} vs {auc_o:.4f})")
        print(f"    複勝率 : {hit1_n - hit1_o:+.1%}  ({hit1_n:.1%} vs {hit1_o:.1%})")
        print(f"    上位3頭: {hit3_n - hit3_o:+.1%}  ({hit3_n:.1%} vs {hit3_o:.1%})")
    else:
        print("  ※ オッズありモデル未発見。trainer.py を先に実行してください。")

    # 学習データ評価（過学習チェック）
    auc_tr, hit1_tr, _ = evaluate_model(model_no_odds, train_df, FEATURE_COLS_NO_ODDS)
    print(f"\n  学習データ: AUC={auc_tr:.4f}  予測1位複勝率={hit1_tr:.1%}")
    print(f"  AUC差(train-val)={auc_tr - auc_n:+.4f}  (小さいほど汎化良好)")

    # 4. 特徴量重要度
    show_importance(model_no_odds)

    # 5. 保存
    model_no_odds.save_model(str(MODEL_PATH_NO_ODDS))
    print(f"\nモデル保存: {MODEL_PATH_NO_ODDS}")
    print(f"総処理時間: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
