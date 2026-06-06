import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect(r'data\keiba.db')
conn.row_factory = sqlite3.Row

print('=== テーブル件数 ===')
for tbl, label in [
    ('horse_results', '馬毎レース成績'),
    ('jockeys',       '騎手マスタ'),
    ('horses',        '馬登録マスタ'),
    ('payouts',       '払戻データ'),
]:
    try:
        n = conn.execute(f'SELECT COUNT(1) FROM {tbl}').fetchone()[0]
        print(f'  {tbl:<20} {n:>10,}  ({label})')
    except Exception as e:
        print(f'  {tbl:<20} (未作成: {e})')

print()
print('=== レース成績 整合性 ===')
print(f'  総レコード: {conn.execute("SELECT COUNT(1) FROM horse_results").fetchone()[0]:,}')
print(f'  ユニーク日: {conn.execute("SELECT COUNT(DISTINCT race_date) FROM horse_results").fetchone()[0]:,}')
print(f'  ユニーク馬: {conn.execute("SELECT COUNT(DISTINCT blood_reg_num) FROM horse_results").fetchone()[0]:,}')
print(f'  ユニーク騎: {conn.execute("SELECT COUNT(DISTINCT jockey_code) FROM horse_results").fetchone()[0]:,}')
print(f'  1着レコード: {conn.execute("SELECT COUNT(1) FROM horse_results WHERE finish_pos=1").fetchone()[0]:,}')
print(f'  上がり3Fあり: {conn.execute("SELECT COUNT(1) FROM horse_results WHERE agari_3f IS NOT NULL").fetchone()[0]:,}')

print()
print('=== レースサマリ (直近5レース) ===')
for row in conn.execute('SELECT * FROM v_race_summary ORDER BY race_date DESC LIMIT 5'):
    print(f'  {row["race_date"]} 会場{row["venue_code"]} R{row["race_num"]}'
          f' {row["starters"]}頭  勝:{row["winner"]} {row["winner_time"]}'
          f' ({row["winner_jockey"]}, {row["winner_popularity"]}番人気)')

print()
print('=== サンプルレコード (horse_results) ===')
row = conn.execute('SELECT * FROM horse_results ORDER BY race_date DESC LIMIT 1').fetchone()
for k in row.keys():
    v = str(row[k])
    if k != 'tail_raw' and k != 'payout_raw':
        print(f'  {k:20s}: {v[:70]}')

print()
print('=== 騎手マスタ サンプル (現役5名) ===')
try:
    for row in conn.execute(
        'SELECT jockey_code, jockey_name, birth_date FROM jockeys WHERE is_active=1 LIMIT 5'
    ):
        print(f'  {row["jockey_code"]} {row["jockey_name"]} 生:{row["birth_date"]}')
except Exception as e:
    print(f'  (エラー: {e})')

print()
print('=== 馬マスタ サンプル ===')
try:
    for row in conn.execute(
        'SELECT blood_reg_num, birth_date, sex_raw, prod_area FROM horses LIMIT 5'
    ):
        print(f'  {row["blood_reg_num"]} 生:{row["birth_date"]} 性:{row["sex_raw"]} {row["prod_area"]}')
except Exception as e:
    print(f'  (エラー: {e})')

print()
print('=== 払戻データ サンプル ===')
try:
    for row in conn.execute(
        'SELECT race_date, venue_code, race_num, starters FROM payouts ORDER BY race_date DESC LIMIT 5'
    ):
        print(f'  {row["race_date"]} 会場{row["venue_code"]} R{row["race_num"]} {row["starters"]}頭')
except Exception as e:
    print(f'  (エラー: {e})')

conn.close()
