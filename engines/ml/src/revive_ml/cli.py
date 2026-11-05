"""Command-line interface: `revive-ml assess <bundle> --out report.json` and helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from revive_ml.contract import ContractError, load_bundle, write_bundle

app = typer.Typer(add_completion=False, help="REVIVE-TERY ML engine (standalone).")


def _dump(obj: object, out: Path | None) -> None:
    text = json.dumps(obj, indent=2, default=str)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def assess(
    bundle: Annotated[Path, typer.Argument(help="bundle directory (metadata.json + telemetry)")],
    out: Annotated[Path | None, typer.Option("--out", help="report JSON path")] = None,
    workloads: Annotated[Path | None, typer.Option(help="YAML file with a 'workloads' mapping")] = None,
) -> None:
    """Assess one battery bundle and write a JSON report."""
    from revive_ml.pipeline import assess as run

    try:
        b = load_bundle(bundle)
    except ContractError as exc:
        typer.echo(f"CONTRACT ERROR: {exc}", err=True)
        raise typer.Exit(2) from exc
    wl = None
    if workloads:
        wl = yaml.safe_load(workloads.read_text(encoding="utf-8"))["workloads"]
    report = run(b, wl)
    _dump(report, out)
    typer.echo(f"decision: {report['decision']}")


@app.command("convert-demo")
def convert_demo_cmd(
    source: Annotated[Path | None, typer.Option(help="demo CSV folder")] = None,
    out: Annotated[Path | None, typer.Option(help="bundle output folder")] = None,
) -> None:
    """Convert the REVIVE-TERY demo CSV bundle (copy in examples/demo_source) to a contract bundle."""
    from revive_ml.convert import DEMO_SOURCE, convert_demo

    p = convert_demo(source or DEMO_SOURCE, out)
    typer.echo(f"wrote {p}")


@app.command("make-synthetic")
def make_synthetic(
    out: Annotated[Path, typer.Option(help="bundle output folder")] = Path(
        "examples/clean_synthetic_bundle"),
    chemistry: str = "LFP",
    seed: int = 0,
) -> None:
    """Write a clean SYNTHETIC bundle (labelled synthetic) that exercises every stage."""
    from revive_ml.synth import NMC_SPEC, PackSpec, make_clean_bundle

    spec = PackSpec() if chemistry == "LFP" else NMC_SPEC
    b = make_clean_bundle(spec, seed=seed)
    write_bundle(out, b.meta, b.telemetry, fmt="csv")
    typer.echo(f"wrote {out}")


@app.command()
def download(
    names: Annotated[list[str] | None, typer.Argument(help="dataset keys (default: all required)")] = None,
    include_optional: bool = False,
) -> None:
    """Download public datasets listed in configs/datasets.yaml (failures are logged, not fatal)."""
    from revive_ml.state.download import download as dl

    status = dl(names or None, include_optional=include_optional)
    for k, v in status.items():
        typer.echo(f"{k}: {v}")


@app.command("validate-dq")
def validate_dq(n: int = 100) -> None:
    """Detection rate on injected faults and false-positive rate on clean synthetic bundles."""
    from revive_ml.dq.validate import write_report

    r = write_report(n)
    for k, d in r["detection"].items():
        typer.echo(f"{k:28s} detected {d['detected']}/{d['trials']}")
    flagged = {k: v["flagged"] for k, v in r["false_positive_rate_per_detector"].items() if v["flagged"]}
    typer.echo(f"false positives on {n} clean bundles: {flagged or 'none'}")
    typer.echo("wrote reports/dq_validation.json")


@app.command("etl")
def etl() -> None:
    """Convert downloaded public datasets to parquet (data/processed/)."""
    from revive_ml.state import etl_nasa

    typer.echo(f"nasa: {etl_nasa.run()}")
    try:
        from revive_ml.state import etl_severson

        typer.echo(f"severson: {etl_severson.run()}")
        from revive_ml.state.features import severson_windows

        w = severson_windows()
        typer.echo(f"severson windows: {len(w)} from {w.cell.nunique()} cells")
    except FileNotFoundError as exc:
        typer.echo(f"severson: skipped ({exc})")


@app.command()
def train() -> None:
    """Train state models with grouped CV and CV+; write models/ and reports/state_metrics.json."""
    from revive_ml.state.train import train as run

    r = run()
    for s in ("field", "full"):
        best = r["rul"][s]["selected"]
        rm = {k: v["rmse"]["value"] for k, v in r["rul"][s].items() if isinstance(v, dict) and "rmse" in v}
        typer.echo(f"RUL {s}: RMSE cycles {rm}; selected {best}")
    iv = r["rul"]["field"]["intervals"]
    typer.echo(f"CV+ measured coverage {iv['measured_coverage']['value']:.3f} "
               f"(nominal {iv['nominal_level']['value']})")


@app.command("physics-check")
def physics_check() -> None:
    """Check the projection against the published trends it uses; write reports/physics_sanity.json."""
    from revive_ml.physics.sanity import run

    r = run()
    for k, v in r["checks"].items():
        typer.echo(f"{k:28s} {'PASS' if v['pass'] else 'FAIL'}")
    t = r["checks"]["temperature"]
    typer.echo(f"life ratio 25 vs 45 degC: {t['life_ratio_25_vs_45c']} (10 degC doubling rule: 4.0)")
    if not r["all_pass"]:
        raise typer.Exit(1)


@app.command()
def sweep() -> None:
    """Illustrative metal-price sensitivity sweep; writes reports/econ_sensitivity.json."""
    from revive_ml.econ.sensitivity import sweep as run

    r = run()
    for chem, v in r["chemistries"].items():
        typer.echo(f"{chem}: Recycle wins at metal-price multipliers (per energy-value multiplier) "
                   f"{v['recycle_wins_at_metal_multipliers']}")
    typer.echo(r["label"])


@app.command("train-gate")
def train_gate() -> None:
    """Train both OOD filters with grouped CV; write models/ and reports/gate_validation.json."""
    from revive_ml.gate.train import train_and_validate

    r = train_and_validate()
    for fam, v in r["families"].items():
        e = v["grouped_cv"]
        det = {k: x["value"] for k, x in e["detection_rate"].items()}
        typer.echo(f"{fam}: clean quarantine {e['clean_quarantine_rate']['value']:.3f}; detection {det}")


if __name__ == "__main__":  # pragma: no cover
    app()
