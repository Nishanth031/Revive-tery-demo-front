"""Copy the project DuckDB database (github.com/Nishanth031/revive-tery-DB) into data/db/ for the web app.

The source file uses DuckDB storage v2.0, which DuckDB-WASM cannot open yet, so the copy is written
in storage v1.0.0 and attached as "revive_tery" (the catalog name the browser opens it under). Tables, rows
and indexes are unchanged.

Usage: python tools/convert_db.py <path to revive_tery.duckdb>
"""
import pathlib
import sys

import duckdb

src = pathlib.Path(sys.argv[1]).resolve()
q = lambda p: p.as_posix().replace("'", "''")
out = pathlib.Path(__file__).resolve().parents[1] / "data" / "db" / "revive_tery.duckdb"
out.unlink(missing_ok=True)
con = duckdb.connect()
con.execute(f"ATTACH '{q(src)}' AS src (READ_ONLY)")
con.execute(f"ATTACH '{q(out)}' AS revive_tery (STORAGE_VERSION 'v1.0.0')")
con.execute("COPY FROM DATABASE src TO revive_tery")
for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'revive_tery' ORDER BY 1").fetchall():
    a = con.execute(f'SELECT count(*) FROM src."{t}"').fetchone()[0]
    b = con.execute(f'SELECT count(*) FROM revive_tery."{t}"').fetchone()[0]
    assert a == b, (t, a, b)
    print(f"{t}: {b} rows")
con.close()
print("wrote", out)
