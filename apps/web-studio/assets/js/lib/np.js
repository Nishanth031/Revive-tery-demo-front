// Small numeric toolkit that mirrors the numpy / pandas behaviour the Python engines rely on.
// Arrays are plain JS arrays or Float64Arrays; missing values are NaN.

export const isFiniteNum = (v) => typeof v === "number" && Number.isFinite(v);

export function toF64(a) {
  const out = new Float64Array(a.length);
  for (let i = 0; i < a.length; i++) {
    const v = a[i];
    out[i] = v === null || v === undefined || v === "" ? NaN : Number(v);
  }
  return out;
}

// ---------------------------------------------------------------- base64 -> typed arrays (little endian)
function b64bytes(s) {
  if (typeof atob === "function") {
    const bin = atob(s);
    const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  return new Uint8Array(Buffer.from(s, "base64"));
}
export function decode(s, dtype) {
  const u = b64bytes(s);
  const buf = u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength);
  switch (dtype) {
    case "<f8": return new Float64Array(buf);
    case "<i4": return new Int32Array(buf);
    case "<i2": return new Int16Array(buf);
    case "u1": return new Uint8Array(buf);
    default: throw new Error(`unknown dtype ${dtype}`);
  }
}

// ---------------------------------------------------------------- reductions
export function sum(a) { let s = 0; for (const v of a) s += v; return s; }
export function nansum(a) { let s = 0; for (const v of a) if (!Number.isNaN(v)) s += v; return s; }
export function mean(a) { return a.length ? sum(a) / a.length : NaN; }
export function nanmean(a) {
  let s = 0, n = 0;
  for (const v of a) if (!Number.isNaN(v)) { s += v; n++; }
  return n ? s / n : NaN;
}
export function nanmax(a) {
  let m = -Infinity, n = 0;
  for (const v of a) if (!Number.isNaN(v)) { if (v > m) m = v; n++; }
  return n ? m : NaN;
}
export function nanmin(a) {
  let m = Infinity, n = 0;
  for (const v of a) if (!Number.isNaN(v)) { if (v < m) m = v; n++; }
  return n ? m : NaN;
}
export function max(a) { let m = -Infinity; for (const v of a) { if (Number.isNaN(v)) return NaN; if (v > m) m = v; } return m; }
export function min(a) { let m = Infinity; for (const v of a) { if (Number.isNaN(v)) return NaN; if (v < m) m = v; } return m; }
export function ptp(a) { return max(a) - min(a); }
/** population standard deviation (numpy default ddof=0) */
export function std(a) {
  const m = mean(a);
  let s = 0;
  for (const v of a) s += (v - m) * (v - m);
  return Math.sqrt(s / a.length);
}
function sortedCopy(a) { return Float64Array.from(a).sort(); }
export function median(a) {
  if (!a.length) return NaN;
  for (const v of a) if (Number.isNaN(v)) return NaN;
  const s = sortedCopy(a), n = s.length, h = n >> 1;
  return n % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}
export function nanmedian(a) { return median(Array.from(a).filter((v) => !Number.isNaN(v))); }

/** numpy.quantile, method "linear" (default) */
export function quantile(a, q) {
  const s = sortedCopy(a), n = s.length;
  const idx = q * (n - 1), lo = Math.floor(idx), hi = Math.min(lo + 1, n - 1), t = idx - lo;
  const x = s[lo], y = s[hi], d = y - x;
  // numpy _lerp: a + (b-a)*t, evaluated from the nearer end
  return t >= 0.5 ? y - d * (1 - t) : x + d * t;
}
/** numpy.quantile on an already sorted array, method "lower" */
export function quantileLowerSorted(s, q) {
  return s[Math.floor(q * (s.length - 1))];
}

// ---------------------------------------------------------------- elementwise helpers
export function diff(a) {
  const out = new Float64Array(Math.max(0, a.length - 1));
  for (let i = 1; i < a.length; i++) out[i - 1] = a[i] - a[i - 1];
  return out;
}
export const sign = (v) => (Number.isNaN(v) ? NaN : v > 0 ? 1 : v < 0 ? -1 : 0);
export function linspace(a, b, n) {
  const out = new Float64Array(n);
  const step = (b - a) / (n - 1);
  for (let i = 0; i < n; i++) out[i] = a + i * step;
  if (n > 1) out[n - 1] = b;
  return out;
}
export const clip = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** cumulative charge in Ah with the trapezoid rule on the actual step; NaN increments count as 0 (nancumsum) */
export function cumAh(i, dt) {
  const out = new Float64Array(i.length);
  let acc = 0;
  for (let k = 1; k < i.length; k++) {
    const inc = 0.5 * (i[k] + i[k - 1]) * dt[k - 1] / 3600.0;
    if (!Number.isNaN(inc)) acc += inc;
    out[k] = acc;
  }
  return out;
}

// ---------------------------------------------------------------- least squares
/** slope and intercept of the least-squares line (numpy.polyfit(x, y, 1)) */
export function polyfit1(x, y) {
  const n = x.length;
  const mx = mean(x), my = mean(y);
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) * (x[i] - mx); }
  const slope = sxy / sxx;
  return [slope, my - slope * mx];
}

/** eigen-decomposition of a symmetric 2x2 matrix [[a, b], [b, d]] */
function eig2(a, b, d) {
  const tr = a + d, det = a * d - b * b;
  const disc = Math.sqrt(Math.max(0, (a - d) * (a - d) / 4 + b * b));
  const l1 = tr / 2 + disc, l2 = tr / 2 - disc;
  let v1;
  if (Math.abs(b) > 1e-300) v1 = [l1 - d, b];
  else v1 = a >= d ? [1, 0] : [0, 1];
  const nv = Math.hypot(v1[0], v1[1]);
  v1 = [v1[0] / nv, v1[1] / nv];
  const v2 = [-v1[1], v1[0]];
  void det;
  return [[l1, v1], [l2, v2]];
}
/** Moore-Penrose pseudo-inverse of a symmetric 2x2 matrix, singular values below rcond*max dropped */
export function pinvSym2(a, b, d, rcond = 1e-15) {
  const e = eig2(a, b, d);
  const smax = Math.max(Math.abs(e[0][0]), Math.abs(e[1][0]));
  let p = [0, 0, 0];
  for (const [l, v] of e) {
    if (Math.abs(l) > rcond * smax && l !== 0) {
      p = [p[0] + v[0] * v[0] / l, p[1] + v[0] * v[1] / l, p[2] + v[1] * v[1] / l];
    }
  }
  return p; // [p00, p01, p11]
}
/** numpy.linalg.lstsq(X, y, rcond=None) for two columns (minimum-norm solution) */
export function lstsq2(x0, x1, y) {
  const m = y.length;
  let a = 0, b = 0, d = 0, g0 = 0, g1 = 0;
  for (let i = 0; i < m; i++) {
    a += x0[i] * x0[i]; b += x0[i] * x1[i]; d += x1[i] * x1[i];
    g0 += x0[i] * y[i]; g1 += x1[i] * y[i];
  }
  // singular values of X are sqrt(eigenvalues of X'X); lstsq cuts at eps * max(M, N) * s_max
  const eps = 2.220446049250313e-16 * Math.max(m, 2);
  const e = eig2(a, b, d);
  const smax = Math.sqrt(Math.max(e[0][0], e[1][0], 0));
  let c0 = 0, c1 = 0;
  for (const [l, v] of e) {
    const s = Math.sqrt(Math.max(l, 0));
    if (s > eps * smax && s > 0) {
      const proj = (v[0] * g0 + v[1] * g1) / l;
      c0 += v[0] * proj; c1 += v[1] * proj;
    }
  }
  return [c0, c1];
}

// ---------------------------------------------------------------- pandas rolling median (center, min_periods)
export function rollingMedianCentered(x, window, minPeriods) {
  const n = x.length, h = Math.floor(window / 2), out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const lo = Math.max(0, i - h), hi = Math.min(n - 1, i + (window - 1 - h));
    const vals = [];
    for (let k = lo; k <= hi; k++) if (!Number.isNaN(x[k])) vals.push(x[k]);
    out[i] = vals.length >= minPeriods ? median(vals) : NaN;
  }
  return out;
}

/** (start, length) of runs of true values */
export function runs(mask) {
  const out = [];
  let start = null;
  for (let k = 0; k < mask.length; k++) {
    if (mask[k] && start === null) start = k;
    else if (!mask[k] && start !== null) { out.push([start, k - start]); start = null; }
  }
  if (start !== null) out.push([start, mask.length - start]);
  return out;
}

export function argmax(a) { let k = 0; for (let i = 1; i < a.length; i++) if (a[i] > a[k]) k = i; return k; }
export function argmin(a) { let k = 0; for (let i = 1; i < a.length; i++) if (a[i] < a[k]) k = i; return k; }

// ---------------------------------------------------------------- Brent root finder (scipy.optimize.brentq)
export function brentq(f, a, b, xtol = 2e-12, rtol = 8.881784197001252e-16, maxiter = 100) {
  let fa = f(a), fb = f(b);
  if (fa * fb > 0) throw new Error("f(a) and f(b) must have different signs");
  if (fa === 0) return a;
  if (fb === 0) return b;
  let c = a, fc = fa, d = b - a, e = d;
  for (let it = 0; it < maxiter; it++) {
    if (fb * fc > 0) { c = a; fc = fa; d = b - a; e = d; }
    if (Math.abs(fc) < Math.abs(fb)) { a = b; b = c; c = a; fa = fb; fb = fc; fc = fa; }
    const tol = 2 * rtol * Math.abs(b) + 0.5 * xtol, m = 0.5 * (c - b);
    if (Math.abs(m) <= tol || fb === 0) return b;
    if (Math.abs(e) >= tol && Math.abs(fa) > Math.abs(fb)) {
      let p, q, r;
      const s = fb / fa;
      if (a === c) { p = 2 * m * s; q = 1 - s; }
      else { q = fa / fc; r = fb / fc; p = s * (2 * m * q * (q - r) - (b - a) * (r - 1)); q = (q - 1) * (r - 1) * (s - 1); }
      if (p > 0) q = -q; else p = -p;
      if (2 * p < Math.min(3 * m * q - Math.abs(tol * q), Math.abs(e * q))) { e = d; d = p / q; }
      else { d = m; e = m; }
    } else { d = m; e = m; }
    a = b; fa = fb;
    b += Math.abs(d) > tol ? d : (m > 0 ? tol : -tol);
    fb = f(b);
  }
  return b;
}

// ---------------------------------------------------------------- seeded random numbers
/** mulberry32: small, fast, seedable PRNG returning floats in [0, 1) */
export function rng(seed) {
  let s = (seed >>> 0) || 0x9e3779b9;
  const next = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  let spare = null;
  next.gauss = (mu = 0, sigma = 1) => {
    if (spare !== null) { const z = spare; spare = null; return mu + sigma * z; }
    let u, v, r;
    do { u = 2 * next() - 1; v = 2 * next() - 1; r = u * u + v * v; } while (r >= 1 || r === 0);
    const k = Math.sqrt(-2 * Math.log(r) / r);
    spare = v * k;
    return mu + sigma * u * k;
  };
  return next;
}

/** Python's round(x, nd): round half to even on the exact binary value */
export function pyRound(x, nd = 0) {
  if (!Number.isFinite(x)) return x;
  if (nd === 0) {
    const f = Math.floor(x), r = x - f;
    if (r > 0.5) return f + 1;
    if (r < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }
  if (Math.abs(x) >= 1e15) return x;
  return Number(x.toFixed(nd));
}
