"""Database verification - field accuracy checks."""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect(r'data\keiba.db')

print("=== 正確なレース数カウント ===")
for sql, label in [
    ("SELECT COUNT(DISTINCT race_date||venue_code||meeting_num||day_num||race_num) FROM horse_results",
     "ユニークレース"),
    ("SELECT COUNT(DISTINCT race_date||venue_code||meeting_num||day_num||race_num) FROM horse_results WHERE finish_pos=1",
     "勝ち馬がいるレース"),
    ("SELECT COUNT(1) FROM horse_results WHERE finish_pos IS NULL", "着順不明(取消等)"),
    ("SELECT COUNT(1) FROM horse_results WHERE finish_pos=1 AND finish_margin=''", "1着+空白着差"),
    ("SELECT COUNT(1) FROM horse_results WHERE finish_pos>1 AND finish_margin=''", "2着以降+空白着差(異常)"),
]:
    print(f"  {label}: {conn.execute(sql).fetchone()[0]:,}")

print()
print("=== 着差コード分布 (top10) ===")
for row in conn.execute("""
    SELECT finish_margin, COUNT(1) as n FROM horse_results
    GROUP BY finish_margin ORDER BY n DESC LIMIT 10
"""):
    print(f"  {row[0]!r:12s}: {row[1]:,}")

print()
print("=== タイム分布 (範囲) ===")
for row in conn.execute("""
    SELECT
        MIN(race_time) as min_t, MAX(race_time) as max_t,
        COUNT(DISTINCT race_time) as distinct_times
    FROM horse_results WHERE race_time != ''
"""):
    print(f"  Min: {row[0]}, Max: {row[1]}, Distinct: {row[2]}")

print()
print("=== 人気1番の複勝率 ===")
row = conn.execute("""
    SELECT
        COUNT(1) as total,
        SUM(CASE WHEN finish_pos=1 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN finish_pos<=3 THEN 1 ELSE 0 END) as places
    FROM horse_results WHERE popularity=1 AND finish_pos IS NOT NULL
""").fetchone()
total, wins, places = row
print(f"  1番人気: {total}頭  単勝率:{wins/total:.1%}  複勝率:{places/total:.1%}")

print()
print("=== コーナー通過順 (4角1位→着順) ===")
for row in conn.execute("""
    SELECT corner4, finish_pos, COUNT(1) as n
    FROM horse_results
    WHERE corner4 IS NOT NULL AND finish_pos IS NOT NULL
      AND corner4 <= 3
    GROUP BY corner4, finish_pos ORDER BY corner4, finish_pos
    LIMIT 12
"""):
    print(f"  4角{row[0]}位→{row[1]}着: {row[2]}回")

print()
print("=== 福島2026-04-13 R1 全頭成績 ===")
for row in conn.execute("""
    SELECT horse_num, horse_name, gate_num, finish_pos, race_time,
           finish_margin, popularity, corner1, corner2, corner3, corner4,
           horse_weight, weight_change, jockey_name
    FROM horse_results
    WHERE race_date='20260413' AND venue_code='03'
      AND meeting_num='01' AND day_num='01' AND race_num='01'
    ORDER BY finish_pos NULLS LAST
"""):
    print(f"  {row[3]:>2}着 枠{row[2]} 馬{row[0]} {row[1]:<12} {row[4]} "
          f"差:{row[5]!r:<6} 人気{row[6]:>2} "
          f"C:{row[7]}-{row[8]}-{row[9]}-{row[10]} "
          f"{row[11]}kg({row[12]}) {row[13]}")

conn.close()
