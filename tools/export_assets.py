"""Export everything the static site needs from the Python projects into data/.

Run with the ML engine's Python (it has scikit-learn, MAPIE and revive_ml installed):

    ..\\revive-tery-ml\\.venv\\Scripts\\python.exe tools\\export_assets.py

What it writes (all plain JSON or copies, nothing secret):
  data/configs.json              dq_rules, limits, physics, economics, workloads (the engine's YAML configs)
  data/models/state_rul.json     5 fold gradient-boosting models + CV+ conformity scores + envelope
  data/models/gate_ood_*.json    IsolationForest trees, scaler, thresholds and envelope (two families)
  data/models/mc_draws.json      the 1,000 physics-parameter draws the Monte Carlo band uses (seed 0)
  data/demo/*.csv                the 8-table demo bundle (DEMO-EV-PACK-001)
  data/samples/*                 the 7 synthetic upload samples
  data/reports/*.json            validation reports; data/docs/*.md model cards and judge Q&A
  data/relife.json               ReLife BMS Studio adapters, scenarios and research catalog
  data/circuit.json              the bench circuit (components and wires) from the dashboard
  data/firmware/*.ino            the ESP32 sketch

Before writing a model it re-implements the model's prediction in numpy, exactly as the browser will,
and asserts it matches scikit-learn / MAPIE. If they disagree the export stops: a wrong number in the
browser is worse than no number.
"""
from __future__ import annotations

import ast
import base64
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
ML = ROOT / "revive-tery-ml"
APP = ROOT / "bulid X"
RELIFE = ROOT / "Hackathon project ev (3)" / "Hackathon project ev"
DATA = WEB / "data"

sys.path.insert(0, str(ML / "src"))
from revive_ml.gate.ood import LOG_FEATURES, load_default  # noqa: E402
from revive_ml.gate.features import FEATURES as GATE_FEATURES  # noqa: E402
from revive_ml.physics.fade import sample_params  # noqa: E402
from revive_ml.state.train import load_model  # noqa: E402

RNG = np.random.default_rng(0)


def b64(arr: np.ndarray, dtype: str) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode("ascii")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), default=str), encoding="utf-8")  # dates -> ISO text
    print(f"  wrote {path.relative_to(WEB)} ({path.stat().st_size / 1024:.0f} KB)")


# --------------------------------------------------------------------------- configs
def export_configs() -> None:
    cfg = {name: yaml.safe_load((ML / "configs" / f"{name}.yaml").read_text(encoding="utf-8"))
           for name in ("dq_rules", "limits", "physics", "economics", "workloads")}
    write_json(DATA / "configs.json", cfg)


# --------------------------------------------------------------------------- gradient boosting + CV+
def hgb_trees(hgb) -> dict:
    """Flatten a fitted HistGradientBoostingRegressor into typed arrays (one entry per node)."""
    feat, thr, left, right, leaf, mleft, value, starts = [], [], [], [], [], [], [], [0]
    for (pred,) in hgb._predictors:
        n = pred.nodes
        assert not n["is_categorical"].any(), "categorical splits are not supported by the exporter"
        feat.append(n["feature_idx"]); thr.append(n["num_threshold"]); left.append(n["left"])
        right.append(n["right"]); leaf.append(n["is_leaf"]); mleft.append(n["missing_go_to_left"])
        value.append(n["value"]); starts.append(starts[-1] + len(n))
    cat = np.concatenate
    return {"baseline": float(np.ravel(hgb._baseline_prediction)[0]), "n_trees": len(starts) - 1,
            "starts": b64(np.array(starts), "<i4"), "feature": b64(cat(feat), "<i2"),
            "threshold": b64(cat(thr), "<f8"), "left": b64(cat(left), "<i4"), "right": b64(cat(right), "<i4"),
            "is_leaf": b64(cat(leaf), "u1"), "missing_left": b64(cat(mleft), "u1"), "value": b64(cat(value), "<f8")}


def hgb_predict_np(hgb, X: np.ndarray) -> np.ndarray:
    """The browser's algorithm, in numpy: walk each tree on raw feature values."""
    out = np.full(len(X), float(np.ravel(hgb._baseline_prediction)[0]))
    for (pred,) in hgb._predictors:
        n = pred.nodes
        for r, x in enumerate(X):
            i = 0
            while not n["is_leaf"][i]:
                v = x[n["feature_idx"][i]]
                go_left = n["missing_go_to_left"][i] if np.isnan(v) else v <= n["num_threshold"][i]
                i = n["left"][i] if go_left else n["right"][i]
            out[r] += n["value"][i]
    return out


def cvplus_np(models, scores, fold_of, X):
    """MAPIE CV+ (method='plus', gamma score, alpha 0.1, mean aggregation), as the browser computes it."""
    preds = np.array([np.expm1(hgb_predict_np(m, X)) for m in models])          # (k, n_test)
    # MAPIE's "mean" averages over training rows, each through its out-of-fold model, so fold
    # models are weighted by their fold sizes, not equally.
    point = preds[fold_of].mean(axis=0)
    n = len(scores)
    q = np.ceil(0.95 * (n + 1)) / n
    lo, hi = np.empty(len(X)), np.empty(len(X))
    for j in range(len(X)):
        dist = preds[fold_of, j] * (1 + scores)                                     # one value per training row
        hi[j] = np.quantile(dist, q, method="lower")
        lo[j] = -np.quantile(-dist, q, method="lower")
    return point, lo, hi


def export_state_model() -> None:
    m = load_model()
    inner = m.conformal._mapie_regressor
    ens = inner.estimator_
    folds = [e.regressor_ for e in ens.estimators_]
    k_ = np.nan_to_num(np.asarray(ens.k_, float), nan=0.0)   # MAPIE stores 1 or NaN
    scores = np.asarray(inner.conformity_scores_, float)
    # k_[i, k] == 1 marks the fold model that did NOT see training row i (its out-of-fold model).
    assert (k_.sum(axis=1) == 1).all(), "expected exactly one out-of-fold model per training row"
    fold_of = k_.argmax(axis=1)

    # verification inputs: real training windows plus perturbed and missing-value variants
    windows = pd.read_parquet(ML / "data" / "processed" / "severson_windows.parquet")
    X = windows[m.features].sample(60, random_state=0).to_numpy(float)
    Xp = X * RNG.normal(1, 0.05, X.shape)
    Xn = X[:10].copy(); Xn[:, m.features.index("ir_ratio")] = np.nan
    Xtest = np.vstack([X, Xp, Xn])
    for fold_model, est in zip(folds, ens.estimators_, strict=True):
        ref = est.predict(pd.DataFrame(Xtest, columns=m.features))
        got = np.expm1(hgb_predict_np(fold_model, Xtest))
        assert np.allclose(ref, got, rtol=1e-9, atol=1e-9), "HGB re-implementation differs from scikit-learn"
    ref = m.predict(pd.DataFrame(Xtest, columns=m.features))
    p, lo, hi = cvplus_np(folds, scores, fold_of, Xtest)
    assert np.allclose(np.clip(p, 0, None), ref["point"], rtol=1e-9), "CV+ point differs from MAPIE"
    assert np.allclose(np.clip(lo, 0, None), ref["lower"], rtol=1e-9), "CV+ lower differs from MAPIE"
    assert np.allclose(hi, ref["upper"], rtol=1e-9), "CV+ upper differs from MAPIE"
    print(f"  state model: numpy re-implementation matches scikit-learn + MAPIE on {len(Xtest)} inputs")

    write_json(DATA / "models" / "state_rul.json", {
        "features": m.features, "chemistry": m.chemistry, "confidence": 0.90,
        "envelope": {k: list(v) for k, v in m.envelope.items()},
        "reference_conditions": m.reference_conditions, "validation": m.validation,
        "folds": [hgb_trees(f) for f in folds],
        "conformity_scores": b64(scores, "<f8"), "fold_of": b64(fold_of, "u1"),
        "target_transform": "log1p", "selected": m.validation.get("selected"),
    })
    write_json(WEB / "tests" / "golden" / "state_inputs.json",
               {"X": [[None if np.isnan(v) else float(v) for v in row] for row in Xtest],
                "point": np.clip(p, 0, None).tolist(), "lower": np.clip(lo, 0, None).tolist(), "upper": hi.tolist()})


# --------------------------------------------------------------------------- IsolationForest gate
def log_some_np(Z: np.ndarray) -> np.ndarray:
    Z = Z.copy()
    for c in LOG_FEATURES:
        j = GATE_FEATURES.index(c)
        Z[:, j] = np.log1p(np.abs(Z[:, j]))
    j = GATE_FEATURES.index("resid_mean_t")
    Z[:, j] = np.sign(Z[:, j]) * np.log1p(np.abs(Z[:, j]))
    return Z


def if_avg_path_length(n: float) -> float:
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (np.log(n - 1.0) + np.euler_gamma) - 2.0 * (n - 1.0) / n


def export_gate(family: str) -> None:
    ood = load_default(family)
    pipe = ood.pipeline
    scaler, forest = pipe.named_steps["scale"], pipe.named_steps["iforest"]
    feat, thr, left, right, starts = [], [], [], [], [0]
    for t, (tree, fmap) in enumerate(zip(forest.estimators_, forest.estimators_features_, strict=True)):
        tr = tree.tree_
        is_leaf = tr.children_left == -1
        leaf_val = forest._decision_path_lengths[t] + forest._average_path_length_per_tree[t] - 1.0
        f = np.where(is_leaf, -1, np.asarray(fmap)[np.maximum(tr.feature, 0)])
        feat.append(f); thr.append(np.where(is_leaf, leaf_val, tr.threshold))
        left.append(tr.children_left); right.append(tr.children_right); starts.append(starts[-1] + tr.node_count)
    denom = len(forest.estimators_) * if_avg_path_length(forest._max_samples)
    cat = np.concatenate
    F, T, L, Rr, S = cat(feat), cat(thr), cat(left), cat(right), np.array(starts)

    def score_np(X: np.ndarray) -> np.ndarray:
        Z = (log_some_np(X) - scaler.mean_) / scaler.scale_
        Z = Z.astype(np.float32).astype(np.float64)          # IsolationForest reads float32
        depth = np.zeros(len(Z))
        for t in range(len(S) - 1):
            off = S[t]
            for r, z in enumerate(Z):
                i = 0
                while F[off + i] >= 0:
                    i = L[off + i] if z[F[off + i]] <= T[off + i] else Rr[off + i]
                depth[r] += T[off + i]
        return -(2.0 ** (-depth / denom))

    # verification on windows from the engine's own synthetic generator plus wilder variants
    from revive_ml.dq.inject import random_clean_bundle
    from revive_ml.gate.ood import bundle_features
    X = pd.concat([bundle_features(random_clean_bundle(s)) for s in range(3)], ignore_index=True)[GATE_FEATURES]
    X = X.sample(min(120, len(X)), random_state=0).to_numpy(float)
    X = np.vstack([X, X[:40] * RNG.normal(1, 0.5, (min(40, len(X)), X.shape[1]))])
    ref = ood.score(pd.DataFrame(X, columns=GATE_FEATURES))
    got = score_np(X)
    assert np.allclose(ref, got, rtol=1e-9, atol=1e-12), f"IsolationForest re-implementation differs ({family})"
    print(f"  gate {family}: numpy re-implementation matches scikit-learn on {len(X)} windows")

    write_json(DATA / "models" / f"gate_ood_{family}.json", {
        "family": family, "features": GATE_FEATURES, "log_features": LOG_FEATURES,
        "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
        "thr_flag": ood.thr_flag, "env_lo": ood.env_lo.tolist(), "env_hi": ood.env_hi.tolist(),
        "denominator": denom, "n_trees": len(S) - 1,
        "starts": b64(S, "<i4"), "feature": b64(F, "<i2"), "value": b64(T, "<f8"),
        "left": b64(L, "<i4"), "right": b64(Rr, "<i4"),
        "training_summary": {k: v for k, v in ood.training_summary.items() if k != "validation"},
        "validation": ood.training_summary.get("validation"),
    })
    write_json(WEB / "tests" / "golden" / f"gate_inputs_{family}.json",
               {"X": X.tolist(), "score": ref.tolist()})


# --------------------------------------------------------------------------- physics draws
def export_mc_draws() -> None:
    cfg = yaml.safe_load((ML / "configs" / "physics.yaml").read_text(encoding="utf-8"))
    draws = sample_params(cfg["monte_carlo"]["n_draws"], cfg["monte_carlo"]["seed"])
    keys = list(draws[0].__dict__)
    write_json(DATA / "models" / "mc_draws.json",
               {"keys": keys, "seed": cfg["monte_carlo"]["seed"],
                "rows": [[getattr(d, k) for k in keys] for d in draws]})


# --------------------------------------------------------------------------- data, docs, reports
def copy_files() -> None:
    for src_dir, dst in ((APP / "database" / "csv_bundle", DATA / "demo"),
                         (APP / "database" / "ml_samples", DATA / "samples"),
                         (ML / "reports", DATA / "reports")):
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                shutil.copy2(f, dst / f.name)
    for f in [ML / "docs" / "judge_qa.md", *sorted((ML / "docs" / "model_cards").glob("*.md"))]:
        shutil.copy2(f, DATA / "docs" / f.name)
    shutil.copy2(APP / "firmware" / "revive_tery_esp32" / "revive_tery_esp32.ino", DATA / "firmware")
    print("  copied demo CSVs, samples, reports, docs and firmware")


def export_circuit() -> None:
    tree = ast.parse((APP / "src" / "app.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("COMPONENTS", "WIRES"):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    comps = [{"id": c[0], "title": c[1], "kind": c[2],
              "pins": [{"id": p[0], "label": p[1], "x": p[2], "y": p[3], "side": p[4]} for p in c[3]]}
             for c in found["COMPONENTS"]]
    wires = [{"from": w[0], "to": w[1], "type": w[2], "description": w[3]} for w in found["WIRES"]]
    legend = []  # the dashboard builds its legend from colour variables; the site draws its own
    write_json(DATA / "circuit.json", {"components": comps, "wires": wires, "legend": legend})


def export_relife() -> None:
    sys.path.insert(0, str(RELIFE))
    import battery_details  # noqa: E402
    import bms_engine as relife  # noqa: E402

    write_json(DATA / "relife.json", {
        "adapters": [a.__dict__ for a in relife.ADAPTERS], "scenarios": relife.SCENARIOS,
        "source_label": relife.SOURCE_LABEL, "pulse_duration_s": relife.PULSE_DURATION_S,
        "pulse_sample_s": relife.PULSE_SAMPLE_S,
        "catalog": [p.to_dict() for p in battery_details.seed_profiles()],
        "research_note": battery_details.RESEARCH_NOTE,
    })
    sys.path.remove(str(RELIFE))


if __name__ == "__main__":
    print("exporting to", DATA)
    export_configs()
    export_state_model()
    export_gate("synthetic_packs")
    export_gate("measured_cells")
    export_mc_draws()
    copy_files()
    export_circuit()
    export_relife()
    print("done")
