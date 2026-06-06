"""
LightGBM 複勝予測モデル学習スクリプト (2026-06-06)

学習:  2011-2023年
検証:  2024-2025年
ターゲット: is_placed (3着以内)

2モデルを出力:
  data/model_placed.lgb       - 全特徴量 (人気あり)
  data/model_placed_pure.lgb  - 人気なし (オッズ系除外)

新特徴量: distance, track_type_enc, venue_int
"""

import sys, sqlite3, time
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH   = Path("data/keiba.db")
MODEL_DIR = Path("data")

RACE_KEY    = ["race_date", "venue_code", "meeting_num", "day_num", "race_num"]
SEX_MAP     = {"10": 1, "20": 2, "30": 3, "40": 4}
TRACK_MAP   = {"芝": 1, "ダート": 2, "障害": 3}
TRAIN_START = "20110101"
TRAIN_END   = "20231231"
VAL_START   = "20240101"
VAL_END     = "20251231"

# ── 全特徴量（人気あり） ──────────────────────────────────────────────────────
FEATURE_COLS = [
    # レース条件 (NEW)
    "distance", "track_type_enc", "venue_int",
    # 馬能力: 過去5走
    *[f"horse_pos_{k}"   for k in range(1, 6)],
    *[f"horse_agari_{k}" for k in range(1, 6)],
    "horse_avg_pos_5", "horse_win_rate_5", "horse_place_rate_5", "horse_avg_agari_5",
    # 馬キャリア・脚質・同会場
    "horse_n_races", "horse_days_last_race", "horse_avg_corner4",
    "horse_venue_avg_pos", "horse_venue_win_rate", "horse_venue_races",
    # レース環境
    "gate_num_int", "horse_num_int", "starters", "popularity",
    # 馬体
    "horse_age_int", "sex_enc", "horse_weight", "weight_change_int",
    # 騎手・調教師
    "jockey_win30", "jockey_place30", "jockey_rides30", "jockey_win60",
    "trainer_win30", "trainer_win60",
    # 調教
    "tr_days_before", "tr_4f_last", "tr_1f_last", "tr_4f_avg14d", "tr_sessions_14d",
]

# 人気なしモデル用 (オッズ系除外)
FEATURE_COLS_PURE = [c for c in FEATURE_COLS if c != "popularity"]

LGB_PARAMS = {
    "objective":         "binary",
    "metric":            "auc",
    "num_leaves":        127,
    "learning_rate":     0.05,
    "min_child_samples": 100,
    "feature_fraction":  0.8,
    "bagging_fraction":  0.8,
    "bagging_freq":      5,
    "lambda_l1":         0.1,
    "lambda_l2":         0.1,
    "n_jobs":            -1,
    "random_state":      42,
    "verbose":           -1,
}


# ── 1. データ読み込み ──────────────────────────────────────────────────────────

def load_results() -> pd.DataFrame:
    sql = """
    SELECT race_date, venue_code, meeting_num, day_num, race_num,
           horse_num, gate_num, blood_reg_num,
           horse_age, sex_code, jockey_code, jockey_name, trainer_name,
           horse_weight, weight_change,
           finish_pos, popularity, corner4, agari_3f,
           distance, track_type
    FROM horse_results
    WHERE finish_pos IS NOT NULL AND blood_reg_num IS NOT NULL
    """
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(sql, conn)

    df["finish_pos"]        = pd.to_numeric(df["finish_pos"],   errors="coerce")
    df["popularity"]        = pd.to_numeric(df["popularity"],   errors="coerce")
    df["agari_3f"]          = pd.to_numeric(df["agari_3f"],     errors="coerce")
    df["corner4"]           = pd.to_numeric(df["corner4"],      errors="coerce")
    df["horse_weight"]      = pd.to_numeric(df["horse_weight"], errors="coerce")
    df["gate_num_int"]      = pd.to_numeric(df["gate_num"],     errors="coerce")
    df["horse_num_int"]     = pd.to_numeric(df["horse_num"],    errors="coerce")
    df["horse_age_int"]     = pd.to_numeric(df["horse_age"],    errors="coerce")
    df["sex_enc"]           = df["sex_code"].map(SEX_MAP).fillna(0).astype("int8")
    df["weight_change_int"] = (
        df["weight_change"].str.strip().replace("", "0")
        .apply(lambda x: float(x) if x else 0.0)
    )
    df["venue_int"]         = pd.to_numeric(df["venue_code"],   errors="coerce")
    df["distance"]          = pd.to_numeric(df["distance"],     errors="coerce")
    df["track_type_enc"]    = df["track_type"].map(TRACK_MAP).fillna(0).astype("int8")

    df.loc[df["agari_3f"] < 25, "agari_3f"] = np.nan
    df["is_placed"] = (df["finish_pos"] <= 3).astype("int8")

    print(f"  distance NaN率: {df['distance'].isna().mean():.1%}")
    print(f"  track_type分布: {df['track_type_enc'].value_counts().to_dict()}")
    return df


# ── 2. 馬能力特徴量（vectorized cumsum） ──────────────────────────────────────

def add_horse_features(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = ["blood_reg_num"] + RACE_KEY + ["horse_num"]
    df = df.sort_values(sort_cols).reset_index(drop=True)
    g  = df.groupby("blood_reg_num", sort=False)

    for k in range(1, 6):
        df[f"horse_pos_{k}"]   = g["finish_pos"].shift(k)
        df[f"horse_agari_{k}"] = g["agari_3f"].shift(k)

    pos_cols   = [f"horse_pos_{k}"   for k in range(1, 6)]
    agari_cols = [f"horse_agari_{k}" for k in range(1, 6)]
    n_valid    = df[pos_cols].notna().sum(axis=1).clip(lower=1)

    df["horse_avg_pos_5"]    = df[pos_cols].mean(axis=1)
    df["horse_win_rate_5"]   = (df[pos_cols] == 1).sum(axis=1) / n_valid
    df["horse_place_rate_5"] = (df[pos_cols] <= 3).sum(axis=1) / n_valid
    df["horse_avg_agari_5"]  = df[agari_cols].mean(axis=1)

    df["horse_n_races"] = g.cumcount()
    prev_date = g["race_date"].shift(1)
    df["horse_days_last_race"] = (
        pd.to_datetime(df["race_date"], format="%Y%m%d")
        - pd.to_datetime(prev_date, format="%Y%m%d", errors="coerce")
    ).dt.days

    df["_c4p"] = g["corner4"].shift(1)
    df["_c4n"] = df.groupby("blood_reg_num", sort=False)["_c4p"].transform(
        lambda x: x.notna().cumsum()
    )
    df["horse_avg_corner4"] = (
        df.groupby("blood_reg_num", sort=False)["_c4p"].cumsum()
        / df["_c4n"].clip(lower=1)
    )
    df.drop(columns=["_c4p", "_c4n"], inplace=True)

    df = df.sort_values(
        ["blood_reg_num", "venue_code"] + RACE_KEY + ["horse_num"]
    ).reset_index(drop=True)
    vg = df.groupby(["blood_reg_num", "venue_code"], sort=False)

    df["horse_venue_races"] = vg.cumcount()
    df["_vp"] = vg["finish_pos"].shift(1)
    df["_vw"] = np.where(df["_vp"].notna(), (df["_vp"] == 1).astype(float), np.nan)

    vg2 = df.groupby(["blood_reg_num", "venue_code"], sort=False)
    df["horse_venue_avg_pos"]  = vg2["_vp"].cumsum() / df["horse_venue_races"].clip(lower=1)
    df["horse_venue_win_rate"] = vg2["_vw"].cumsum() / df["horse_venue_races"].clip(lower=1)
    df.loc[df["horse_venue_races"] == 0, "horse_venue_avg_pos"] = np.nan
    df.drop(columns=["_vp", "_vw"], inplace=True)

    return df


# ── 3. レース特徴量 ────────────────────────────────────────────────────────────

def add_race_features(df: pd.DataFrame) -> pd.DataFrame:
    starters = (
        df.groupby(RACE_KEY)["horse_num"].count().rename("starters").reset_index()
    )
    return df.merge(starters, on=RACE_KEY, how="left")


# ── 4. 騎手・調教師（cumsum + searchsorted） ───────────────────────────────────

def _build_cumsum_lookup(df: pd.DataFrame, key_col: str) -> dict:
    daily = (
        df[df["finish_pos"].notna()]
        .groupby([key_col, "race_date"])
        .agg(rides=("finish_pos", "count"),
             wins =("finish_pos", lambda x: (x == 1).sum()),
             places=("finish_pos", lambda x: (x <= 3).sum()))
        .reset_index()
        .sort_values([key_col, "race_date"])
    )
    g = daily.groupby(key_col, sort=False)
    daily["cum_r"] = g["rides"].cumsum()
    daily["cum_w"] = g["wins"].cumsum()
    daily["cum_p"] = g["places"].cumsum()

    lookup = {}
    for key, grp in daily.groupby(key_col, sort=False):
        lookup[key] = (
            grp["race_date"].values,
            grp["cum_r"].values.astype(float),
            grp["cum_w"].values.astype(float),
            grp["cum_p"].values.astype(float),
        )
    return lookup


def _query_window(lookup, key, rdate, d30, d60):
    if key not in lookup:
        return np.nan, np.nan, 0, np.nan
    dates, cum_r, cum_w, cum_p = lookup[key]
    end = int(np.searchsorted(dates, rdate, side="left")) - 1
    if end < 0:
        return np.nan, np.nan, 0, np.nan
    s30 = int(np.searchsorted(dates, d30, side="left")) - 1
    s60 = int(np.searchsorted(dates, d60, side="left")) - 1
    er, ew, ep = cum_r[end], cum_w[end], cum_p[end]
    sr30 = cum_r[s30] if s30 >= 0 else 0.0
    sw30 = cum_w[s30] if s30 >= 0 else 0.0
    sp30 = cum_p[s30] if s30 >= 0 else 0.0
    sr60 = cum_r[s60] if s60 >= 0 else 0.0
    sw60 = cum_w[s60] if s60 >= 0 else 0.0
    r30 = er - sr30; w30 = ew - sw30; p30 = ep - sp30
    r60 = er - sr60; w60_v = ew - sw60
    win30  = w30 / r30 if r30 > 0 else np.nan
    plc30  = p30 / r30 if r30 > 0 else np.nan
    win60  = w60_v / r60 if r60 > 0 else np.nan
    return win30, plc30, int(r30), win60


def add_jockey_features(target: pd.DataFrame, all_results: pd.DataFrame) -> pd.DataFrame:
    lookup = _build_cumsum_lookup(all_results, "jockey_code")
    dt   = pd.to_datetime(target["race_date"], format="%Y%m%d")
    d30s = (dt - pd.Timedelta(days=30)).dt.strftime("%Y%m%d").values
    d60s = (dt - pd.Timedelta(days=60)).dt.strftime("%Y%m%d").values
    w30, p30, r30, w60 = [], [], [], []
    for jcode, rdate, d30, d60 in zip(
        target["jockey_code"].values, target["race_date"].values, d30s, d60s
    ):
        a, b, c, d = _query_window(lookup, jcode, rdate, d30, d60)
        w30.append(a); p30.append(b); r30.append(c); w60.append(d)
    target = target.copy()
    target["jockey_win30"]   = w30
    target["jockey_place30"] = p30
    target["jockey_rides30"] = r30
    target["jockey_win60"]   = w60
    return target


def add_trainer_features(target: pd.DataFrame, all_results: pd.DataFrame) -> pd.DataFrame:
    lookup = _build_cumsum_lookup(all_results, "trainer_name")
    dt   = pd.to_datetime(target["race_date"], format="%Y%m%d")
    d30s = (dt - pd.Timedelta(days=30)).dt.strftime("%Y%m%d").values
    d60s = (dt - pd.Timedelta(days=60)).dt.strftime("%Y%m%d").values
    w30, w60 = [], []
    for tname, rdate, d30, d60 in zip(
        target["trainer_name"].values, target["race_date"].values, d30s, d60s
    ):
        a, _, _, d = _query_window(lookup, tname, rdate, d30, d60)
        w30.append(a); w60.append(d)
    target = target.copy()
    target["trainer_win30"] = w30
    target["trainer_win60"] = w60
    return target


# ── 5. 調教特徴量（searchsorted） ─────────────────────────────────────────────

def add_training_features(target: pd.DataFrame) -> pd.DataFrame:
    sql = """
    SELECT blood_reg_num, training_date, time_4f, time_1f_last
    FROM training WHERE time_4f IS NOT NULL
    ORDER BY blood_reg_num, training_date, training_time
    """
    with sqlite3.connect(DB_PATH) as conn:
        tr = pd.read_sql(sql, conn)

    target_bloods = set(target["blood_reg_num"].unique())
    tr = tr[tr["blood_reg_num"].isin(target_bloods)]
    tr["time_4f"]      = pd.to_numeric(tr["time_4f"],      errors="coerce")
    tr["time_1f_last"] = pd.to_numeric(tr["time_1f_last"], errors="coerce")

    by_horse = {}
    for blood, grp in tr.groupby("blood_reg_num", sort=False):
        by_horse[blood] = {
            "dates":   grp["training_date"].values,
            "time_4f": grp["time_4f"].values,
            "time_1f": grp["time_1f_last"].values,
        }

    dt   = pd.to_datetime(target["race_date"], format="%Y%m%d")
    d14s = (dt - pd.Timedelta(days=14)).dt.strftime("%Y%m%d").values

    tr_days, tr_4f, tr_1f, tr_avg14, tr_n14 = [], [], [], [], []
    for blood, rdate, d14 in zip(
        target["blood_reg_num"].values, target["race_date"].values, d14s
    ):
        if blood not in by_horse:
            tr_days.append(np.nan); tr_4f.append(np.nan)
            tr_1f.append(np.nan);   tr_avg14.append(np.nan); tr_n14.append(0)
            continue
        h   = by_horse[blood]
        idx = int(np.searchsorted(h["dates"], rdate, side="left")) - 1
        if idx < 0:
            tr_days.append(np.nan); tr_4f.append(np.nan)
            tr_1f.append(np.nan);   tr_avg14.append(np.nan); tr_n14.append(0)
            continue
        last_date = h["dates"][idx]
        days      = (pd.Timestamp(rdate) - pd.Timestamp(last_date)).days
        s14  = int(np.searchsorted(h["dates"], d14, side="left"))
        w_4f = h["time_4f"][s14 : idx + 1]
        valid = w_4f[~np.isnan(w_4f)]
        tr_days.append(days); tr_4f.append(h["time_4f"][idx])
        tr_1f.append(h["time_1f"][idx])
        tr_avg14.append(float(valid.mean()) if len(valid) > 0 else np.nan)
        tr_n14.append(int(idx - s14 + 1))

    target = target.copy()
    target["tr_days_before"]  = tr_days
    target["tr_4f_last"]      = tr_4f
    target["tr_1f_last"]      = tr_1f
    target["tr_4f_avg14d"]    = tr_avg14
    target["tr_sessions_14d"] = tr_n14
    return target


# ── 6. LightGBM 学習 ──────────────────────────────────────────────────────────

def train_model(train_df, val_df, feature_cols, label):
    X_tr = train_df[feature_cols]
    y_tr = train_df["is_placed"]
    X_va = val_df[feature_cols]
    y_va = val_df["is_placed"]

    dtrain = lgb.Dataset(X_tr, label=y_tr, feature_name=list(feature_cols))
    dval   = lgb.Dataset(X_va, label=y_va, reference=dtrain)

    print(f"\n{'='*52}")
    print(f"  学習: {label}")
    print(f"  特徴量: {len(feature_cols)}個")
    print(f"{'='*52}")

    model = lgb.train(
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
    return model


# ── 7. 評価 ───────────────────────────────────────────────────────────────────

def evaluate(model, df, feature_cols, label):
    prob = model.predict(df[feature_cols])
    auc  = roc_auc_score(df["is_placed"], prob)

    df2 = df[RACE_KEY + ["is_placed"]].copy()
    df2["prob"] = prob

    top1 = (
        df2.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False).head(1)
    )
    hit1 = top1["is_placed"].mean()

    top3 = (
        df2.sort_values("prob", ascending=False)
        .groupby(RACE_KEY, sort=False).head(3)
    )
    hit3 = top3.groupby(RACE_KEY)["is_placed"].max().mean()

    baseline = df["is_placed"].mean()

    print(f"\n{'='*52}")
    print(f"  {label}")
    print(f"{'='*52}")
    print(f"  AUC                   : {auc:.4f}")
    print(f"  複勝率(全体ベース)    : {baseline:.1%}")
    print(f"  予測1位馬の複勝率     : {hit1:.1%}  (lift {hit1/baseline:.2f}x)")
    print(f"  上位3頭いずれか複勝   : {hit3:.1%}")
    return auc, hit1


def show_importance(model, feature_cols, top_n=10):
    imp = pd.DataFrame({
        "feature": model.feature_name(),
        "gain":    model.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    max_gain = imp["gain"].max()
    print(f"\n  特徴量重要度 TOP {top_n}")
    print(f"  {'feature':<30} {'gain':>12}")
    print(f"  {'-'*44}")
    for _, row in imp.head(top_n).iterrows():
        bar = "█" * max(1, int(row["gain"] / max_gain * 20))
        print(f"  {row['feature']:<30} {row['gain']:>12,.0f}  {bar}")
    return imp


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    T = lambda msg: print(f"\n[{time.time()-t0:>5.1f}s] {msg}")

    T("horse_results 読み込み中…")
    df = load_results()
    print(f"       {len(df):,}行")

    T("馬能力特徴量 (vectorized cumsum)…")
    df = add_horse_features(df)

    T("レース特徴量…")
    df = add_race_features(df)

    target = df[df["race_date"] >= TRAIN_START].copy()
    T(f"騎手特徴量 (searchsorted, {len(target):,}行)…")
    target = add_jockey_features(target, df)

    T("調教師特徴量…")
    target = add_trainer_features(target, df)

    T("調教タイム特徴量…")
    target = add_training_features(target)

    train_df = target[target["race_date"] <= TRAIN_END].copy()
    val_df   = target[
        (target["race_date"] >= VAL_START) & (target["race_date"] <= VAL_END)
    ].copy()

    T("データ準備完了")
    print(f"       学習: {len(train_df):,}行  is_placed={train_df['is_placed'].mean():.1%}")
    print(f"       検証: {len(val_df):,}行    is_placed={val_df['is_placed'].mean():.1%}")
    print(f"       全特徴量: {len(FEATURE_COLS)}個  (人気あり)")
    print(f"       純特徴量: {len(FEATURE_COLS_PURE)}個  (人気なし)")

    # ── model_placed (全特徴量・人気あり) ─────────────────────────────────────
    T("=== model_placed (人気あり) 学習 ===")
    model_full = train_model(train_df, val_df, FEATURE_COLS, "model_placed")

    T("=== model_placed_pure (人気なし) 学習 ===")
    model_pure = train_model(train_df, val_df, FEATURE_COLS_PURE, "model_placed_pure")

    # ── 評価・比較 ─────────────────────────────────────────────────────────────
    print("\n\n" + "="*52)
    print("  ★ 評価結果比較 (2024-2025検証)")
    print("="*52)

    auc_f, hit_f = evaluate(model_full, val_df, FEATURE_COLS,      "model_placed     (人気あり)")
    auc_p, hit_p = evaluate(model_pure, val_df, FEATURE_COLS_PURE, "model_placed_pure (人気なし)")

    print("\n\n" + "="*52)
    print("  学習データ評価 (2011-2023)")
    print("="*52)
    evaluate(model_full, train_df, FEATURE_COLS,      "model_placed     [TRAIN]")
    evaluate(model_pure, train_df, FEATURE_COLS_PURE, "model_placed_pure [TRAIN]")

    # ── 特徴量重要度 ───────────────────────────────────────────────────────────
    print("\n\n" + "="*52)
    print("  特徴量重要度 model_placed (人気あり)")
    show_importance(model_full, FEATURE_COLS)

    print("\n" + "="*52)
    print("  特徴量重要度 model_placed_pure (人気なし)")
    show_importance(model_pure, FEATURE_COLS_PURE)

    # ── 比較サマリー ───────────────────────────────────────────────────────────
    print("\n\n" + "="*52)
    print("  ★ 最終比較サマリー")
    print("="*52)
    print(f"  {'モデル':<24} {'AUC':>6}  {'予測1位複勝率':>12}")
    print(f"  {'-'*46}")
    print(f"  {'model_placed (人気あり)':<24} {auc_f:.4f}  {hit_f:.1%}")
    print(f"  {'model_placed_pure (人気なし)':<24} {auc_p:.4f}  {hit_p:.1%}")
    prev_auc = 0.81
    print(f"\n  前回AUC: {prev_auc:.2f}")
    status = "✓ 上回った!" if max(auc_f, auc_p) > prev_auc else "△ 変化なし"
    print(f"  今回最良: {max(auc_f, auc_p):.4f}  {status}")

    # ── 保存 ──────────────────────────────────────────────────────────────────
    path_full = MODEL_DIR / "model_placed.lgb"
    path_pure = MODEL_DIR / "model_placed_pure.lgb"
    model_full.save_model(str(path_full))
    model_pure.save_model(str(path_pure))
    T(f"保存完了: {path_full.name}, {path_pure.name}")
    print(f"  総処理時間: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
