// Full ML engine parity: the browser port must reach the same decisions and numbers as revive-tery-ml (Python).
import { test } from "node:test";
import assert from "node:assert/strict";
import { golden, assets, close, bundleFromGolden } from "./helpers.mjs";
import { assess } from "../assets/js/engines/pipeline.js";

const cases = golden("pipeline_cases.json");

for (const [name, c] of Object.entries(cases)) {
  test(`pipeline parity: ${name}`, async () => {
    const A = await assets();
    const bundle = await bundleFromGolden(c.bundle);
    const got = assess(bundle, A);
    const ref = c.report;
    assert.equal(got.decision, ref.decision, "decision");
    assert.equal(got.data_quality.readiness.verdict, ref.data_quality.readiness.verdict, "readiness");
    ref.data_quality.checks.forEach((rc, k) => {
      const gc = got.data_quality.checks[k];
      assert.equal(gc.id, rc.id);
      assert.equal(gc.status, rc.status, `${rc.id} status (${gc.message} | ${rc.message})`);
      assert.equal(gc.severity, rc.severity, `${rc.id} severity`);
      assert.equal(gc.message, rc.message, `${rc.id} message`);
    });
    assert.deepEqual(got.rationale, ref.rationale, "rationale");
    assert.deepEqual(got.warnings, ref.warnings, "warnings");
    if (ref.gate) {
      assert.equal(got.gate.verdict, ref.gate.verdict, "gate verdict");
      assert.deepEqual(got.gate.reasons, ref.gate.reasons, "gate reasons");
      if (ref.gate.ood.n_windows !== undefined) {
        assert.equal(got.gate.ood.n_windows, ref.gate.ood.n_windows, "windows");
        assert.equal(got.gate.ood.n_flagged_windows, ref.gate.ood.n_flagged_windows, "flagged windows");
        assert.equal(got.gate.ood.n_outside_envelope_windows, ref.gate.ood.n_outside_envelope_windows, "outside envelope");
      }
    }
    if (ref.state) {
      assert.equal(got.state.status, ref.state.status);
      for (const [k, v] of Object.entries(ref.state.features || {})) close(got.state.features[k].value, v.value, `feature ${k}`, 1e-6, 1e-6);
      if (ref.state.rul_cycles_reference) {
        close(got.state.rul_cycles_reference.value, ref.state.rul_cycles_reference.value, "rul point", 1e-6);
        close(got.state.rul_cycles_reference.lower, ref.state.rul_cycles_reference.lower, "rul lower", 1e-6);
        close(got.state.rul_cycles_reference.upper, ref.state.rul_cycles_reference.upper, "rul upper", 1e-6);
      }
    }
    if (ref.projections) {
      for (const [w, p] of Object.entries(ref.projections)) {
        const gp = got.projections[w];
        close(gp.conservative_years.value, p.conservative_years.value, `${w} conservative years`, 1e-5, 1e-5);
        for (const [k, t] of Object.entries(p.years_to_application_limit)) close(gp.years_to_application_limit[k].value, t.value, `${w} ${k}`, 1e-5, 1e-5);
        p.points.forEach((pt, i) => {
          close(gp.points[i].soh.value, pt.soh.value, `${w} soh y${i}`, 1e-6, 1e-6);
          close(gp.points[i].mc_band.values[0], pt.mc_band.values[0], `${w} mc lo y${i}`, 1e-5, 1e-3);
          close(gp.points[i].mc_band.values[1], pt.mc_band.values[1], `${w} mc hi y${i}`, 1e-5, 1e-3);
          close(gp.points[i].ml_band.values[0], pt.ml_band.values[0], `${w} ml lo y${i}`, 1e-5, 1e-3);
        });
      }
    }
    if (ref.economics) {
      for (const [w, o] of Object.entries(ref.economics.second_life_options)) close(got.economics.second_life_options[w].net_value.value, o.net_value.value, `${w} net`, 1e-6, 1e-3);
      close(got.economics.recycle.net_value.value, ref.economics.recycle.net_value.value, "recycle net");
      assert.deepEqual(got.economics.placeholder_inputs, ref.economics.placeholder_inputs);
      assert.deepEqual(got.comparison_with_existing_rule, ref.comparison_with_existing_rule);
    }
  });
}
