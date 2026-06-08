"""SQLite schema for keiba-ai database."""

import sqlite3
from pathlib import Path

DB_PATH = Path(r"C:\Users\effor\keiba-ai\data\keiba.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS horse_results (
    -- Primary key
    race_date       TEXT NOT NULL,   -- YYYYMMDD
    venue_code      TEXT NOT NULL,   -- 2-digit JRA venue code
    meeting_num     TEXT NOT NULL,   -- 開催回次
    day_num         TEXT NOT NULL,   -- 開催日次
    race_num        TEXT NOT NULL,   -- レース番号
    horse_num       TEXT NOT NULL,   -- 馬番

    -- Horse entry
    gate_num        TEXT,
    blood_reg_num   TEXT,

    -- Horse info
    horse_name      TEXT,
    horse_age       TEXT,
    sex_code        TEXT,
    coat_code       TEXT,

    -- People
    jockey_name     TEXT,
    jockey_code     TEXT,
    trainer_name    TEXT,
    owner_name      TEXT,

    -- Appearance
    silks_desc      TEXT,

    -- Physical condition
    horse_weight    INTEGER,         -- kg
    weight_change   TEXT,            -- "+002", "-018", etc.

    -- Race result
    finish_pos      INTEGER,         -- 着順 (1-18)
    race_time       TEXT,            -- "M:SS.T"
    finish_margin   TEXT,            -- 着差 (K=ハナ, A=アタマ, H=クビ, etc.)
    popularity      INTEGER,         -- 人気

    -- 4-corner passage positions
    corner1         INTEGER,
    corner2         INTEGER,
    corner3         INTEGER,
    corner4         INTEGER,

    -- 上がり3ハロン (last 3 furlongs time, seconds)
    agari_3f        REAL,

    -- Winner reference stored in each horse's record
    winner_blood_reg TEXT,
    winner_name      TEXT,

    -- Course / distance (decoded from pos 537-538, race-level)
    track_type      TEXT,    -- '芝', 'ダート', '障害'
    dist_class      TEXT,    -- raw code '0'-'5' (distance class within track type)
    distance        INTEGER, -- approximate distance in meters

    -- Raw tail bytes (pos 439-552) for future field discovery
    tail_raw        TEXT,

    -- Source
    source_file     TEXT,

    PRIMARY KEY (race_date, venue_code, meeting_num, day_num, race_num, horse_num)
);

CREATE INDEX IF NOT EXISTS idx_hr_date      ON horse_results(race_date);
CREATE INDEX IF NOT EXISTS idx_hr_blood     ON horse_results(blood_reg_num);
CREATE INDEX IF NOT EXISTS idx_hr_jockey    ON horse_results(jockey_code);
CREATE INDEX IF NOT EXISTS idx_hr_horse     ON horse_results(horse_name);
CREATE INDEX IF NOT EXISTS idx_hr_finish    ON horse_results(finish_pos);
CREATE INDEX IF NOT EXISTS idx_hr_popularity ON horse_results(popularity);
CREATE INDEX IF NOT EXISTS idx_hr_agari     ON horse_results(agari_3f);

-- ─────────────────────────────────────────────────────
-- Jockey master (from TFJ_KISI.DAT)
CREATE TABLE IF NOT EXISTS jockeys (
    jockey_code  TEXT PRIMARY KEY,
    jockey_name  TEXT,
    name_kana    TEXT,
    birth_date   TEXT,
    license_date TEXT,   -- デビュー日
    retire_date  TEXT,   -- 引退日 (NULL if active)
    is_active    INTEGER DEFAULT 1
);

-- Horse registration master (from UM_DATA SK files)
-- Note: horse names are in horse_results; this table has bio info
CREATE TABLE IF NOT EXISTS horses (
    blood_reg_num TEXT PRIMARY KEY,
    birth_date    TEXT,
    sex_raw       TEXT,
    coat_raw      TEXT,
    prod_area     TEXT,   -- 産地
    update_date   TEXT
);
CREATE INDEX IF NOT EXISTS idx_horses_birth ON horses(birth_date);
CREATE INDEX IF NOT EXISTS idx_horses_prod  ON horses(prod_area);

-- Race payouts (from HY_DATA HY1*.DAT, 1 record per race)
CREATE TABLE IF NOT EXISTS payouts (
    race_date   TEXT NOT NULL,
    venue_code  TEXT NOT NULL,
    meeting_num TEXT NOT NULL,
    day_num     TEXT NOT NULL,
    race_num    TEXT NOT NULL,
    starters    INTEGER,
    finishers   INTEGER,
    race_class  TEXT,
    payout_raw  TEXT,   -- hex of bytes 100-516 (future analysis)
    source_file TEXT,
    PRIMARY KEY (race_date, venue_code, meeting_num, day_num, race_num)
);

-- Pedigree table (from UM_DATA SK + KT_DATA KT2)
-- Covers parents (父/母) + grandparents (父父/父母/母父/母母) + great-grandparents
CREATE TABLE IF NOT EXISTS pedigree (
    blood_reg_num TEXT PRIMARY KEY,

    -- Level 1: parents
    father_uid    TEXT,  father_name   TEXT,   -- 父
    mother_uid    TEXT,  mother_name   TEXT,   -- 母

    -- Level 2: grandparents
    pat_gf_uid    TEXT,  pat_gf_name   TEXT,   -- 父父
    pat_gm_uid    TEXT,  pat_gm_name   TEXT,   -- 父母
    mat_gf_uid    TEXT,  mat_gf_name   TEXT,   -- 母父
    mat_gm_uid    TEXT,  mat_gm_name   TEXT,   -- 母母

    -- Level 3: great-grandparents
    ppgf_uid TEXT, ppgf_name TEXT,   -- 父父父
    ppgm_uid TEXT, ppgm_name TEXT,   -- 父父母
    pmgf_uid TEXT, pmgf_name TEXT,   -- 父母父
    pmgm_uid TEXT, pmgm_name TEXT,   -- 父母母
    mpgf_uid TEXT, mpgf_name TEXT,   -- 母父父
    mpgm_uid TEXT, mpgm_name TEXT,   -- 母父母
    mmgf_uid TEXT, mmgf_name TEXT,   -- 母母父
    mmgm_uid TEXT, mmgm_name TEXT    -- 母母母
);
CREATE INDEX IF NOT EXISTS idx_ped_father ON pedigree(father_uid);
CREATE INDEX IF NOT EXISTS idx_ped_mother ON pedigree(mother_uid);
CREATE INDEX IF NOT EXISTS idx_ped_mat_gf ON pedigree(mat_gf_uid);  -- 母父 is key for racing

-- Training data (from CK_DATA HC02/HC12 files)
-- Field layout (47-char ASCII fixed-width records):
--   [0]     : data class ('0' or '1')
--   [1-8]   : training_date YYYYMMDD
--   [9-12]  : training_time HHMM (morning session clock time)
--   [13-22] : blood_reg_num (10-digit horse ID)
--   [23-24] : venue_code (05=東京, 06=中山, 07=中京, 08=京都, 09=阪神)
--   [25-34] : extra_raw (unknown fields: course type, condition, etc.)
--   [35-37] : time_4f_raw (4-furlong time, tenths of seconds)
--   [38-40] : time_2f_raw (2-furlong time, tenths of seconds)
--   [41-43] : time_1f_a_raw (1-furlong first measurement, tenths)
--   [44-46] : time_1f_b_raw (1-furlong second/last measurement, tenths)
CREATE TABLE IF NOT EXISTS training (
    training_date   TEXT NOT NULL,   -- YYYYMMDD
    training_time   TEXT NOT NULL,   -- HHMM
    blood_reg_num   TEXT NOT NULL,   -- 10-digit horse ID
    venue_code      TEXT,            -- 05-09 (JRA venue code)
    time_4f         REAL,            -- 4-furlong time (seconds, NULL if 0)
    time_2f         REAL,            -- 2-furlong time (seconds, NULL if 0)
    time_1f_first   REAL,            -- 1-furlong first measurement (seconds)
    time_1f_last    REAL,            -- 1-furlong last/final measurement
    extra_raw       TEXT,            -- raw [25-34] for future analysis
    source_file     TEXT,
    PRIMARY KEY (training_date, training_time, blood_reg_num)
);
CREATE INDEX IF NOT EXISTS idx_tr_date     ON training(training_date);
CREATE INDEX IF NOT EXISTS idx_tr_blood    ON training(blood_reg_num);
CREATE INDEX IF NOT EXISTS idx_tr_venue    ON training(venue_code);
CREATE INDEX IF NOT EXISTS idx_tr_4f       ON training(time_4f);
CREATE INDEX IF NOT EXISTS idx_tr_1f       ON training(time_1f_last);

-- ─────────────────────────────────────────────────────────────────────────
-- Entry data from ES_DATA (TF-JV 出馬表, LR/LU files)
-- Populated by load_entries.py after morning TF-JV update

CREATE TABLE IF NOT EXISTS entries (
    -- Race key
    race_date       TEXT NOT NULL,   -- YYYYMMDD
    venue_code      TEXT NOT NULL,   -- 2-digit (NAR: 30=門別, 42=浦和, 43=船橋, ...)
    meeting_num     TEXT NOT NULL,   -- 開催回次
    day_num         TEXT NOT NULL,   -- 開催日次
    race_num        TEXT NOT NULL,   -- レース番号

    -- Race info (from LR/RAA records)
    race_name       TEXT,            -- レース名 (full Japanese name)
    grade_code      TEXT,            -- 'A'=GⅠ, ...'E'=特別, ' '=一般
    distance        INTEGER,         -- 距離 m (NULL if not in file)
    track_type      TEXT,            -- '芝', 'ダート', '障害' (RA2 byte 705: 1/2/3)
    condition_text  TEXT,            -- ASCII conditions e.g. "TOKUBETSU(3YO)"

    -- Horse entry (from LU/SEA records)
    horse_num       TEXT NOT NULL,   -- 馬番
    gate_num        TEXT,            -- 枠番
    blood_reg_num   TEXT,
    horse_name      TEXT,
    horse_age       INTEGER,
    sex_code        TEXT,            -- '1'=牡, '2'=牝, '3'=騸 (single digit)
    jockey_name     TEXT,
    jockey_code     TEXT,
    trainer_name    TEXT,
    body_weight     INTEGER,         -- 馬体重 kg (last known; NULL if unknown)

    -- Source
    source_file     TEXT,
    loaded_at       TEXT DEFAULT (datetime('now', 'localtime')),

    PRIMARY KEY (race_date, venue_code, meeting_num, day_num, race_num, horse_num)
);

CREATE INDEX IF NOT EXISTS idx_entries_date       ON entries(race_date);
CREATE INDEX IF NOT EXISTS idx_entries_venue      ON entries(race_date, venue_code);
CREATE INDEX IF NOT EXISTS idx_entries_blood      ON entries(blood_reg_num);
CREATE INDEX IF NOT EXISTS idx_entries_jockey     ON entries(jockey_code);

-- Quick race view
CREATE VIEW IF NOT EXISTS v_race_entries AS
SELECT
    race_date,
    venue_code,
    meeting_num,
    day_num,
    race_num,
    horse_num,
    gate_num,
    horse_name,
    jockey_name,
    trainer_name,
    horse_age,
    sex_code,
    horse_weight,
    weight_change,
    finish_pos,
    race_time,
    finish_margin,
    popularity,
    corner1, corner2, corner3, corner4,
    track_type,
    dist_class,
    distance
FROM horse_results
ORDER BY race_date, venue_code, race_num, horse_num;

-- Race summary
CREATE VIEW IF NOT EXISTS v_race_summary AS
SELECT
    race_date,
    venue_code,
    meeting_num,
    day_num,
    race_num,
    COUNT(1) AS starters,
    MAX(CASE WHEN finish_pos=1 THEN horse_name END) AS winner,
    MAX(CASE WHEN finish_pos=1 THEN race_time  END) AS winner_time,
    MAX(CASE WHEN finish_pos=1 THEN jockey_name END) AS winner_jockey,
    MAX(CASE WHEN finish_pos=1 THEN popularity  END) AS winner_popularity
FROM horse_results
GROUP BY race_date, venue_code, meeting_num, day_num, race_num
ORDER BY race_date, venue_code, race_num;
"""


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = get_conn(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
