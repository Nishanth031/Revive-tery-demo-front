#!/usr/bin/env python3
"""Copy the legacy project folders into the platform layout (read-only on the legacy side).

    python scripts/migrate_from_legacy.py                 # dry run: prints the plan, copies nothing
    python scripts/migrate_from_legacy.py --apply         # copy
    python scripts/migrate_from_legacy.py --apply --force # overwrite existing destinations
    python scripts/migrate_from_legacy.py --legacy-base "D:/path/to/Bulid X" --apply

The legacy base defaults to the folder that contains this platform folder. The manifest is
scripts/migration_manifest.json. The script never modifies, moves or deletes anything in the legacy folders.
Standard library only. Re-running is safe: files that already exist are kept unless --force.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def excluded(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def walk_files(src: Path, patterns: list[str]):
    if src.is_file():
        yield src
        return
    for p in src.rglob("*"):
        rel_parts = p.relative_to(src).parts
        if any(excluded(part, patterns) for part in rel_parts):
            continue
        if p.is_file():
            yield p


def copy_entry(src: Path, dst: Path, patterns: list[str], force: bool) -> tuple[int, int, int]:
    """Merge-copy: existing destination files are kept unless force. Returns (copied, bytes, kept)."""
    copied = size = kept = 0
    pairs = [(src, dst)] if src.is_file() else [(f, dst / f.relative_to(src)) for f in walk_files(src, patterns)]
    for f, target in pairs:
        if target.exists() and not force:
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        copied += 1
        size += f.stat().st_size
    return copied, size, kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--legacy-base", type=Path, default=PLATFORM.parent)
    ap.add_argument("--manifest", type=Path, default=PLATFORM / "scripts" / "migration_manifest.json")
    ap.add_argument("--apply", action="store_true", help="actually copy (default is a dry run)")
    ap.add_argument("--force", action="store_true", help="overwrite destination files that already exist")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    roots = manifest["legacy_roots"]
    patterns = manifest["global_exclude"]
    base = args.legacy_base.resolve()
    print(f"Legacy base : {base}\nPlatform    : {PLATFORM}\nMode        : {'APPLY' if args.apply else 'DRY RUN'}\n")

    missing, skipped, done = [], [], []
    total_files = total_size = 0
    for item in manifest["copies"]:
        key, _, rest = item["src"].partition("/")
        if key not in roots:
            print(f"ERROR unknown root '{key}' in {item['src']}")
            return 2
        src = base / roots[key] / rest if rest else base / roots[key]
        dst = (PLATFORM / item["dst"]).resolve()
        if PLATFORM not in dst.parents and dst != PLATFORM:
            print(f"ERROR destination escapes the platform folder: {item['dst']}")
            return 2
        if not src.exists():
            (skipped if item.get("optional") else missing).append(item["src"])
            continue
        files = list(walk_files(src, patterns))
        n, sz = len(files), sum(f.stat().st_size for f in files)
        print(f"  {'copy' if args.apply else 'would copy'}: {item['src']:<48} -> {item['dst']}  [{n} files, {human(sz)}]")
        if args.apply:
            _, _, kept = copy_entry(src, dst, patterns, args.force)
            if kept:
                skipped.append(f"{item['dst']}: {kept} file(s) already existed and were kept (use --force to overwrite)")
        done.append(item["src"])
        total_files += n
        total_size += sz

    print(f"\n{len(done)} entries, {total_files} files, {human(total_size)} "
          f"{'copied' if args.apply else 'would be copied'}.")
    if skipped:
        print("Skipped:", *skipped, sep="\n  ")
    if missing:
        print("MISSING sources (check the legacy base or the manifest):", *missing, sep="\n  ")
        return 1
    if not args.apply:
        print("\nDry run only. Re-run with --apply to copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
