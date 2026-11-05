#!/usr/bin/env python3
"""Impact check: "I changed these files, what do I have to re-run?"

Usage:
    python scripts/impact.py                      # uses `git diff --name-only HEAD` plus untracked files
    python scripts/impact.py engines/ml/src/revive_ml/gate/ood.py apps/web-studio/assets/js/app.js

Reads registry.json (the single source of truth for dependencies) and prints, in order:
which components you touched, which components depend on them, and the commands to run.
Standard library only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_registry() -> dict:
    return json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))


def git_changed() -> list[str]:
    cmds = (["git", "diff", "--name-only", "HEAD"], ["git", "ls-files", "--others", "--exclude-standard"])
    out: list[str] = []
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        out += [line for line in res.stdout.splitlines() if line.strip()]
    return sorted(set(out))


def owner(path: str, components: list[dict]) -> str | None:
    """Component whose longest registered path prefix matches the file."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    best, best_len = None, -1
    for comp in components:
        for prefix in comp["paths"]:
            if (path == prefix or path.startswith(prefix)) and len(prefix) > best_len:
                best, best_len = comp["id"], len(prefix)
    return best


def downstream(start: set[str], by_id: dict[str, dict]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        cur = todo.pop()
        for consumer in by_id[cur]["consumers"]:
            if consumer not in seen and consumer in by_id:
                seen.add(consumer)
                todo.append(consumer)
    return seen - start


def main(argv: list[str]) -> int:
    reg = load_registry()
    comps = reg["components"]
    by_id = {c["id"]: c for c in comps}
    files = argv or git_changed()
    if not files:
        print("No changed files found (pass paths as arguments, or run inside a git repo).")
        return 0

    touched: set[str] = set()
    unmapped: list[str] = []
    for f in files:
        cid = owner(f, comps)
        if cid:
            touched.add(cid)
        else:
            unmapped.append(f)

    affected = downstream(touched, by_id)
    print(f"Changed files: {len(files)}")
    print(f"Touched components : {', '.join(sorted(touched)) or '-'}")
    print(f"Downstream affected: {', '.join(sorted(affected)) or '-'}")
    if unmapped:
        shown = ", ".join(unmapped[:8]) + (" ..." if len(unmapped) > 8 else "")
        print(f"Not in registry.json ({len(unmapped)}): {shown}")
        print("  -> add a path for these in registry.json if they belong to a component.")

    print("\nRun, in this order:")
    step = 1
    for cid in [*sorted(touched), *sorted(affected)]:
        comp = by_id[cid]
        label = "changed" if cid in touched else "downstream"
        regen = comp.get("regenerate_when_upstream_changes")
        # A changed engine feeds the JS ports: regenerate them first (that list ends with the tests).
        if cid in affected and regen and "web-studio" not in touched:
            for cmd in regen:
                print(f"  {step}. [{cid} / regenerate+test] {cmd}")
                step += 1
            continue
        for cmd in comp["on_change"]:
            print(f"  {step}. [{cid} / {label}] {cmd}")
            step += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
