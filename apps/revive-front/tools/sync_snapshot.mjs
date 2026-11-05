// Copies the studio's generated, read-only snapshot files into apps/revive-front/data/.
// The originals are only read (fs.copyFile); nothing in apps/web-studio is changed.
import { copyFile, mkdir, readdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../web-studio/data");
const dst = resolve(here, "../data");
const FILES = ["fleet_reports.json", "db_meta.json", "history.json", "decision_map.json", "configs.json"];

await mkdir(join(dst, "docs"), { recursive: true });
for (const f of FILES) { await copyFile(join(src, f), join(dst, f)); console.log("copied", f); }
for (const f of (await readdir(join(src, "docs"))).filter((n) => n.endsWith(".md"))) {
  await copyFile(join(src, "docs", f), join(dst, "docs", f));
  console.log("copied docs/" + f);
}

// The full engine studio (Circuit Studio, ReLife BMS, Live assessment, DQ Lab, engine status...) embedded under studio/.
import { cp } from "node:fs/promises";
const studioSrc = resolve(here, "../../web-studio"), studioDst = resolve(here, "../studio");
for (const p of ["index.html", "assets", "data"]) await cp(join(studioSrc, p), join(studioDst, p), { recursive: true });
console.log("copied web-studio -> studio/");
