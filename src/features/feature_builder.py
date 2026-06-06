"""
Feature builder for LightGBM horse racing prediction.

All features use only data strictly BEFORE the target race_date (no leakage).

Feature groups
--------------
horse_*    individual horse ability (past 5 races, same-venue record,
           running style, career context)
entry_*    per-entry characteristics (age, sex, weight)
race_*     race-level environment (starters, gate/horse number)
jockey_*   jockey 30-day / 60-day win & place rates
trainer_*  trainer 30-day / 60-day win rates
tr_*       pre-race training times and session counts

Targets
-------
finish_pos : raw finish order (integer)
is_win     : 1 if finish_pos == 1
is_placed  : 1 if finish_pos <= 3

Performance notes
-----------------
Horse ability features use vectorized cumsum (not expanding lambda).
Jockey/trainer features loop over unique race dates (~25/month), not rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_DB_PATH = Path(__file__).parents[2] / "data" / "keiba.db"

_RACE_KEY = ["race_date", "venue_code", "meeting_num", "day_num", "race_num"]
_SEX_MAP  = {"10": 1, "20": 2, "30": 3, "40": 4}


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_race_time(t: Optional[str]) -> Optional[float]:
    """'1:46.7' → 106.7 seconds. None on failure."""
    if not t or not isinstance(t, str):
        return None
    try:
        m, s = t.strip().split(":") if ":" in t else ("0", t.strip())
        return int(m) * 60 + float(s)
    except ValueError:
        return None


def _parse_weight_change(w: Optional[str]) -> float:
    """+002 → 2, -018 → -18, spaces/empty → 0."""
    if not w:
        return 0.0
    try:
        return float(str(w).strip())
    except ValueError:
        return 0.0


# ── feature builder ───────────────────────────────────────────────────────────

class FeatureBuilder:
    def __init__(self, db_path: str | Path = _DB_PATH) -> None:
        self.db_path = Path(db_path)

    # ── public API ────────────────────────────────────────────────────────────

    def build_dataset(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Return a DataFrame (one row per race entry) enriched with features.
        Only historical data before each row's race_date is used.

        Parameters
        ----------
        start_date, end_date : 'YYYYMMDD' (inclusive)
        """
        print("Loading results …")
        results = self._load_results()

        print("Horse ability features …")
        results = self._add_horse_features(results)

        print("Race-level features …")
        results = self._add_race_features(results)

        print(f"Filtering to {start_date}–{end_date} …")
        target = results[
            (results["race_date"] >= start_date)
            & (results["race_date"] <= end_date)
        ].copy()

        if target.empty:
            return target

        print("Jockey features …")
        target = self._add_jockey_features(target, results)

        print("Trainer features …")
        target = self._add_trainer_features(target, results)

        print("Training features …")
        target = self._add_training_features(target)

        target["is_win"]    = (target["finish_pos"] == 1).astype(np.int8)
        target["is_placed"] = (target["finish_pos"] <= 3).astype(np.int8)

        print(f"Done: {len(target):,} rows × {len(target.columns)} cols")
        return target.reset_index(drop=True)

    # ── data loading ──────────────────────────────────────────────────────────

    _TRACK_TYPE_ENC = {"芝": 1, "ダート": 2, "障害": 3}

    def _load_results(self) -> pd.DataFrame:
        sql = """
        SELECT
            race_date, venue_code, meeting_num, day_num, race_num,
            horse_num, gate_num, blood_reg_num,
            horse_name, horse_age, sex_code,
            jockey_name, jockey_code, trainer_name,
            horse_weight, weight_change,
            finish_pos, race_time, popularity,
            corner1, corner2, corner3, corner4,
            agari_3f, distance, track_type
        FROM horse_results
        WHERE finish_pos IS NOT NULL
          AND blood_reg_num IS NOT NULL
        """
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(sql, conn)

        df["race_time_sec"]     = df["race_time"].apply(_parse_race_time)
        df["weight_change_int"] = df["weight_change"].apply(_parse_weight_change)
        df["gate_num_int"]      = pd.to_numeric(df["gate_num"],    errors="coerce")
        df["horse_num_int"]     = pd.to_numeric(df["horse_num"],   errors="coerce")
        df["horse_age_int"]     = pd.to_numeric(df["horse_age"],   errors="coerce")
        df["sex_enc"]           = df["sex_code"].map(_SEX_MAP).fillna(0).astype(np.int8)
        df["horse_weight"]      = pd.to_numeric(df["horse_weight"], errors="coerce")
        df["finish_pos"]        = pd.to_numeric(df["finish_pos"],   errors="coerce")
        df["popularity"]        = pd.to_numeric(df["popularity"],   errors="coerce")
        df["agari_3f"]          = pd.to_numeric(df["agari_3f"],     errors="coerce")
        df["corner4"]           = pd.to_numeric(df["corner4"],      errors="coerce")
        df["venue_int"]         = pd.to_numeric(df["venue_code"],   errors="coerce")
        df["distance"]          = pd.to_numeric(df["distance"],     errors="coerce")
        df["track_type_enc"]    = df["track_type"].map(self._TRACK_TYPE_ENC).fillna(0).astype(np.int8)
        return df

    # ── horse ability (vectorized cumsum — no expanding lambda) ───────────────

    def _add_horse_features(self, df: pd.DataFrame) -> pd.DataFrame:
        # ── 1. Sort by horse + chronological order ───────────────────────────
        sort_cols = ["blood_reg_num"] + _RACE_KEY + ["horse_num"]
        df = df.sort_values(sort_cols).reset_index(drop=True)
        g  = df.groupby("blood_reg_num", sort=False)

        # ── 2. Past 5 finish positions & agari ───────────────────────────────
        for k in range(1, 6):
            df[f"horse_pos_{k}"]   = g["finish_pos"].shift(k)
            df[f"horse_agari_{k}"] = g["agari_3f"].shift(k)

        pos_cols   = [f"horse_pos_{k}"   for k in range(1, 6)]
        agari_cols = [f"horse_agari_{k}" for k in range(1, 6)]

        pos_mat   = df[pos_cols]
        agari_mat = df[agari_cols]
        n_valid   = pos_mat.notna().sum(axis=1).clip(lower=1)

        df["horse_avg_pos_5"]    = pos_mat.mean(axis=1)
        df["horse_win_rate_5"]   = (pos_mat == 1).sum(axis=1) / n_valid
        df["horse_place_rate_5"] = (pos_mat <= 3).sum(axis=1) / n_valid
        df["horse_avg_agari_5"]  = agari_mat.mean(axis=1)

        # ── 3. Career context ────────────────────────────────────────────────
        df["horse_n_races"] = g.cumcount()  # 0 = debut

        prev_date = g["race_date"].shift(1)
        df["horse_days_last_race"] = (
            pd.to_datetime(df["race_date"], format="%Y%m%d")
            - pd.to_datetime(prev_date,     format="%Y%m%d", errors="coerce")
        ).dt.days

        # ── 4. Running style: avg corner4 (vectorized cumsum) ────────────────
        df["_c4_prev"]   = g["corner4"].shift(1)
        df["_c4_cumsum"] = g["_c4_prev"].cumsum()
        df["_c4_n"]      = g["_c4_prev"].transform(lambda x: x.notna().cumsum())
        df["horse_avg_corner4"] = df["_c4_cumsum"] / df["_c4_n"].clip(lower=1)
        df.drop(columns=["_c4_prev", "_c4_cumsum", "_c4_n"], inplace=True)

        # ── 5. Same-venue performance (sorted by blood+venue+date) ───────────
        df = df.sort_values(
            ["blood_reg_num", "venue_code"] + _RACE_KEY + ["horse_num"]
        ).reset_index(drop=True)
        vg = df.groupby(["blood_reg_num", "venue_code"], sort=False)

        df["horse_venue_races"] = vg.cumcount()

        # Shift finish_pos within (horse, venue) group, then grouped cumsum
        df["_vp"] = vg["finish_pos"].shift(1)
        # Use np.where to keep float64 dtype (bool.where(NaN) → object dtype)
        df["_vw"] = np.where(df["_vp"].notna(), (df["_vp"] == 1).astype(float), np.nan)

        vg2 = df.groupby(["blood_reg_num", "venue_code"], sort=False)
        df["_vp_cs"] = vg2["_vp"].cumsum()
        df["_vw_cs"] = vg2["_vw"].cumsum()

        df["horse_venue_avg_pos"]  = df["_vp_cs"] / df["horse_venue_races"].clip(lower=1)
        df["horse_venue_win_rate"] = df["_vw_cs"] / df["horse_venue_races"].clip(lower=1)
        # First venue race has no prior data → NaN
        df.loc[df["horse_venue_races"] == 0, "horse_venue_avg_pos"] = np.nan

        df.drop(columns=["_vp", "_vw", "_vp_cs", "_vw_cs"], inplace=True)

        return df

    # ── race-level features ───────────────────────────────────────────────────

    def _add_race_features(self, df: pd.DataFrame) -> pd.DataFrame:
        starters = (
            df.groupby(_RACE_KEY)["horse_num"]
            .count()
            .rename("starters")
            .reset_index()
        )
        df = df.merge(starters, on=_RACE_KEY, how="left")
        # Relative running position at corner 4
        df["horse_corner4_rel"] = df["corner4"] / df["starters"].clip(lower=1)
        return df

    # ── jockey features (loop over unique dates, not rows) ───────────────────

    def _add_jockey_features(
        self, target: pd.DataFrame, all_results: pd.DataFrame
    ) -> pd.DataFrame:

        daily = (
            all_results[all_results["finish_pos"].notna()]
            .groupby(["jockey_code", "race_date"], sort=False)
            .agg(
                rides  =("finish_pos", "count"),
                wins   =("finish_pos", lambda x: (x == 1).sum()),
                places =("finish_pos", lambda x: (x <= 3).sum()),
            )
            .reset_index()
        )
        daily["date_dt"] = pd.to_datetime(daily["race_date"], format="%Y%m%d")

        chunks = []
        for tdate in sorted(target["race_date"].unique()):
            tdt    = pd.Timestamp(tdate)
            start30 = (tdt - pd.Timedelta(days=30)).strftime("%Y%m%d")
            start60 = (tdt - pd.Timedelta(days=60)).strftime("%Y%m%d")

            def _agg(mask):
                return daily[mask].groupby("jockey_code", sort=False).agg(
                    rides=("rides","sum"),
                    wins =("wins", "sum"),
                    places=("places","sum"),
                ).reset_index()

            w30 = _agg((daily["race_date"] < tdate) & (daily["race_date"] >= start30))
            w60 = _agg((daily["race_date"] < tdate) & (daily["race_date"] >= start60))

            w30["jockey_win30"]   = w30["wins"]   / w30["rides"].clip(lower=1)
            w30["jockey_place30"] = w30["places"] / w30["rides"].clip(lower=1)
            w30["jockey_rides30"] = w30["rides"]

            w60["jockey_win60"] = w60["wins"] / w60["rides"].clip(lower=1)

            merged = w30[["jockey_code","jockey_win30","jockey_place30","jockey_rides30"]].merge(
                w60[["jockey_code","jockey_win60"]], on="jockey_code", how="outer"
            )
            merged["race_date"] = tdate
            chunks.append(merged)

        if chunks:
            stats = pd.concat(chunks, ignore_index=True)
            target = target.merge(
                stats[["jockey_code","race_date","jockey_win30","jockey_place30",
                        "jockey_rides30","jockey_win60"]],
                on=["jockey_code","race_date"], how="left",
            )
        return target

    # ── trainer features (same pattern as jockey) ─────────────────────────────

    def _add_trainer_features(
        self, target: pd.DataFrame, all_results: pd.DataFrame
    ) -> pd.DataFrame:

        daily = (
            all_results[all_results["finish_pos"].notna()]
            .groupby(["trainer_name", "race_date"], sort=False)
            .agg(
                rides =("finish_pos", "count"),
                wins  =("finish_pos", lambda x: (x == 1).sum()),
            )
            .reset_index()
        )

        chunks = []
        for tdate in sorted(target["race_date"].unique()):
            start30 = (pd.Timestamp(tdate) - pd.Timedelta(days=30)).strftime("%Y%m%d")
            start60 = (pd.Timestamp(tdate) - pd.Timedelta(days=60)).strftime("%Y%m%d")

            def _agg(mask):
                return daily[mask].groupby("trainer_name", sort=False).agg(
                    rides=("rides","sum"), wins=("wins","sum")
                ).reset_index()

            w30 = _agg((daily["race_date"] < tdate) & (daily["race_date"] >= start30))
            w60 = _agg((daily["race_date"] < tdate) & (daily["race_date"] >= start60))

            w30["trainer_win30"] = w30["wins"] / w30["rides"].clip(lower=1)
            w60["trainer_win60"] = w60["wins"] / w60["rides"].clip(lower=1)

            merged = w30[["trainer_name","trainer_win30"]].merge(
                w60[["trainer_name","trainer_win60"]], on="trainer_name", how="outer"
            )
            merged["race_date"] = tdate
            chunks.append(merged)

        if chunks:
            stats = pd.concat(chunks, ignore_index=True)
            target = target.merge(
                stats[["trainer_name","race_date","trainer_win30","trainer_win60"]],
                on=["trainer_name","race_date"], how="left",
            )
        return target

    # ── training features ─────────────────────────────────────────────────────

    def _add_training_features(self, target: pd.DataFrame) -> pd.DataFrame:
        horses = tuple(target["blood_reg_num"].unique())
        phs    = ",".join("?" * len(horses))
        sql    = f"""
        SELECT blood_reg_num, training_date, time_4f, time_1f_last
        FROM training
        WHERE blood_reg_num IN ({phs})
          AND time_4f IS NOT NULL
        ORDER BY blood_reg_num, training_date DESC, training_time DESC
        """
        with sqlite3.connect(self.db_path) as conn:
            tr = pd.read_sql(sql, conn, params=list(horses))

        tr["time_4f"]      = pd.to_numeric(tr["time_4f"],      errors="coerce")
        tr["time_1f_last"] = pd.to_numeric(tr["time_1f_last"], errors="coerce")

        by_horse: dict[str, pd.DataFrame] = {
            b: g.reset_index(drop=True)
            for b, g in tr.groupby("blood_reg_num", sort=False)
        }

        rows = []
        for blood, rdate in zip(target["blood_reg_num"], target["race_date"]):
            if blood not in by_horse:
                rows.append((np.nan, np.nan, np.nan, np.nan, 0))
                continue

            g      = by_horse[blood]
            before = g[g["training_date"] < rdate]

            if before.empty:
                rows.append((np.nan, np.nan, np.nan, np.nan, 0))
                continue

            last = before.iloc[0]
            days = (pd.Timestamp(rdate) - pd.Timestamp(last["training_date"])).days

            cut14 = (pd.Timestamp(rdate) - pd.Timedelta(days=14)).strftime("%Y%m%d")
            w14   = before[before["training_date"] >= cut14]

            rows.append((
                days,
                last["time_4f"],
                last["time_1f_last"],
                w14["time_4f"].mean() if not w14.empty else np.nan,
                len(w14),
            ))

        target = target.copy()
        (target["tr_days_before"],
         target["tr_4f_last"],
         target["tr_1f_last"],
         target["tr_4f_avg14d"],
         target["tr_sessions_14d"]) = zip(*rows)

        return target

    # ── feature column list ───────────────────────────────────────────────────

    @staticmethod
    def feature_columns() -> list[str]:
        """Ordered list of model input feature names (no target / ID cols)."""
        return [
            # race conditions (new: distance & track type)
            "distance",
            "track_type_enc",
            "venue_int",
            # horse ability – past 5 races
            *[f"horse_pos_{k}"   for k in range(1, 6)],
            *[f"horse_agari_{k}" for k in range(1, 6)],
            "horse_avg_pos_5",
            "horse_win_rate_5",
            "horse_place_rate_5",
            "horse_avg_agari_5",
            # horse career & style
            "horse_n_races",
            "horse_days_last_race",
            "horse_avg_corner4",
            # same-venue record
            "horse_venue_avg_pos",
            "horse_venue_win_rate",
            "horse_venue_races",
            # race environment
            "gate_num_int",
            "horse_num_int",
            "starters",
            "popularity",
            # entry characteristics
            "horse_age_int",
            "sex_enc",
            "horse_weight",
            "weight_change_int",
            # jockey
            "jockey_win30",
            "jockey_place30",
            "jockey_rides30",
            "jockey_win60",
            # trainer
            "trainer_win30",
            "trainer_win60",
            # training
            "tr_days_before",
            "tr_4f_last",
            "tr_1f_last",
            "tr_4f_avg14d",
            "tr_sessions_14d",
        ]

    @staticmethod
    def pure_feature_columns() -> list[str]:
        """Feature columns without odds-related fields (popularity)."""
        return [c for c in FeatureBuilder.feature_columns() if c != "popularity"]
