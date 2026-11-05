// The project database in the browser: data/db/revive_tery.duckdb (from github.com/Nishanth031/revive-tery-DB),
// opened read-only with DuckDB-WASM. The engines read their tables from it; the Backend page queries it.
import { toCSV, parseCSV } from "./csv.js";

export const DUCKDB_WASM_VERSION = "1.29.0";
export const DB_FILE = "data/db/revive_tery.duckdb";
const CDN = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${DUCKDB_WASM_VERSION}`;

let handle = null;

/** open the database once; resolves to { db, conn, duckdb, version, bytes } */
export function openDatabase(timeoutMs = 30000) {
  if (!handle) {
    handle = withTimeout(open(), timeoutMs, `DuckDB-WASM did not start within ${timeoutMs / 1000} s`);
    handle.catch(() => { handle = null; });
  }
  return handle;
}

async function open() {
  const [duckdb, bytes] = await Promise.all([
    import(/* webpackIgnore: true */ `${CDN}/+esm`),
    fetch(DB_FILE).then((r) => { if (!r.ok) throw new Error(`${DB_FILE}: HTTP ${r.status}`); return r.arrayBuffer(); }),
  ]);
  const size = bytes.byteLength; // measured now: the buffer is transferred to the worker below
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl));
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  await db.registerFileBuffer("revive_tery.duckdb", new Uint8Array(bytes));
  await db.open({ path: "revive_tery.duckdb", accessMode: duckdb.DuckDBAccessMode.READ_ONLY });
  const conn = await db.connect();
  const version = await scalarQuery(conn, "SELECT version()");
  return { db, conn, duckdb, version, bytes: size };
}

function withTimeout(p, ms, message) {
  return Promise.race([p, new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms))]);
}

const ident = (s) => `"${String(s).replace(/"/g, '""')}"`;

/** run SQL; rows come back as plain objects (BigInt → Number when safe) */
export async function query(conn, sql) {
  const result = await conn.query(sql);
  const fields = result.schema.fields;
  const cols = fields.map((f) => f.name);
  const kind = Object.fromEntries(fields.map((f) => [f.name, /^Timestamp/i.test(String(f.type)) ? "ts" : /^Date/i.test(String(f.type)) ? "date" : null]));
  const rows = result.toArray().map((r) => {
    const o = {};
    for (const c of cols) {
      let v = r[c];
      if (typeof v === "bigint") v = Number.isSafeInteger(Number(v)) ? Number(v) : v.toString();
      if (v !== null && v !== undefined && kind[c]) {
        const iso = new Date(Number(v)).toISOString();
        v = kind[c] === "date" ? iso.slice(0, 10) : iso.replace(/\.000Z$/, "Z");
      }
      o[c] = v;
    }
    return o;
  });
  return { cols, rows };
}
async function scalarQuery(conn, sql) { const { cols, rows } = await query(conn, sql); return rows.length ? rows[0][cols[0]] : null; }

export async function listTables(conn) {
  const { rows } = await query(conn, "SELECT table_name, estimated_size FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name");
  return rows;
}

/**
 * Read one table as the same rows the CSV files give: every column is rendered to text in SQL
 * (timestamps as UTC ISO-8601 with Z, dates as YYYY-MM-DD) and then parsed by the app's CSV reader,
 * so the engines see identical values whichever source the data came from.
 */
export async function readTable(conn, table) {
  const { rows: info } = await query(conn, `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'main' AND table_name = '${table.replace(/'/g, "''")}' ORDER BY ordinal_position`);
  if (!info.length) throw new Error(`table ${table} is not in the database`);
  const cols = info.map((c) => c.column_name);
  const select = info.map(({ column_name: c, data_type: t }) => {
    const id = ident(c);
    if (/^TIMESTAMP WITH TIME ZONE/.test(t)) return `strftime(CAST(${id} AS TIMESTAMP), '%Y-%m-%dT%H:%M:%SZ') AS ${id}`; // no ICU extension in the browser build: the cast is in UTC
    if (/^TIMESTAMP/.test(t)) return `strftime(${id}, '%Y-%m-%dT%H:%M:%S') AS ${id}`;
    if (t === "DATE") return `strftime(${id}, '%Y-%m-%d') AS ${id}`;
    return `CAST(${id} AS VARCHAR) AS ${id}`;
  }).join(", ");
  const { rows } = await query(conn, `SELECT ${select} FROM ${ident(table)}`);
  if (!rows.length) return [];
  return parseCSV(toCSV(cols, rows)).rows;
}
