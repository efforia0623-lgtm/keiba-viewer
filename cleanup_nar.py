import sqlite3
from pathlib import Path

DB_PATH = Path("data/keiba.db")
conn = sqlite3.connect(DB_PATH)

before = conn.execute("SELECT COUNT(1) FROM entries").fetchone()[0]
print(f"削除前: {before:,} 件")

conn.execute("DELETE FROM entries WHERE venue_code NOT BETWEEN '01' AND '10'")
conn.commit()

after = conn.execute("SELECT COUNT(1) FROM entries").fetchone()[0]
print(f"削除後: {after:,} 件  (削除: {before - after:,} 件)")

size_before = DB_PATH.stat().st_size / 1024 / 1024
conn.execute("VACUUM")
conn.commit()
size_after = DB_PATH.stat().st_size / 1024 / 1024
print(f"DBサイズ: {size_before:.1f} MB → {size_after:.1f} MB")

conn.close()
