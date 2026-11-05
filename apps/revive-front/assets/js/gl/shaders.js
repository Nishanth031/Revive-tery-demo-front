// L0 fragment shader: domain-warped fbm mixing maroon-950/700 with green-950/800, faint paper veins, vignette, dither.
export const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }
`;

export const FRAG = `
precision highp float;
varying vec2 vUv;
uniform float uTime;
uniform float uScroll;   // 0..1 page progress
uniform vec2 uMouse;     // -1..1
uniform float uTone;     // 0 maroon-led .. 1 green-led
uniform vec2 uRes;

const vec3 M950 = vec3(0.1216, 0.0157, 0.0353);
const vec3 M700 = vec3(0.3608, 0.0588, 0.1333);
const vec3 G950 = vec3(0.0157, 0.0902, 0.0588);
const vec3 G800 = vec3(0.0431, 0.2392, 0.1725);
const vec3 P100 = vec3(0.9569, 0.9333, 0.8902);

float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  mat2 r = mat2(0.8, -0.6, 0.6, 0.8);
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = r * p * 2.02; a *= 0.5; }
  return v;
}

void main() {
  vec2 uv = vUv;
  vec2 p = (uv - 0.5) * vec2(uRes.x / uRes.y, 1.0) * 2.2;
  float t = uTime * 0.035;
  p += uMouse * 0.06;
  p.y += uScroll * 1.4;
  vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3) - t));
  vec2 r = vec2(fbm(p + 3.0 * q + vec2(1.7, 9.2) + t * 0.6), fbm(p + 3.0 * q + vec2(8.3, 2.8) - t * 0.4));
  float f = fbm(p + 2.6 * r);

  vec3 maroon = mix(M950, M700, smoothstep(0.35, 0.95, f));
  vec3 green = mix(G950, G800, smoothstep(0.3, 0.9, f));
  float g = smoothstep(0.25, 0.85, r.x + uTone * 0.6 - 0.15);
  vec3 col = mix(maroon, green, g * (0.55 + 0.4 * uTone));

  // faint paper veins along the warp ridges
  float vein = 1.0 - smoothstep(0.0, 0.018, abs(fract(f * 6.0 + q.y) - 0.5) * 0.08 + abs(r.y - 0.5) * 0.05);
  col = mix(col, P100, vein * 0.045);

  // vignette
  float d = length((uv - 0.5) * vec2(1.1, 1.0));
  col *= mix(1.0, 0.45, smoothstep(0.35, 0.95, d));

  // dither against banding
  col += (hash(gl_FragCoord.xy + fract(uTime)) - 0.5) / 255.0;
  gl_FragColor = vec4(col, 1.0);
}
`;
