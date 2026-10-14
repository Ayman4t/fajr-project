// Simulated test for speed-adjusted pitch scoring.
// Run:  node test/speed-sim.js
// It extracts the REAL scoring code (between PURE-START / PURE-END) from index.html
// and simulates a reciter who follows each ayah's reference contour at 1x, 0.75x and 0.5x.
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const m = html.match(/\/\*PURE-START[\s\S]*?\*\/([\s\S]*?)\/\*PURE-END\*\//);
if (!m) throw new Error("PURE block not found in index.html");
const L = new Function(m[1] + "; return {yin,H,fold,stepRec,newQ,scoreOf};")();
const quran = JSON.parse(fs.readFileSync(path.join(root, "data/quran.json"), "utf8"));

let fails = 0;
const ok = (c, msg) => { console.log((c ? "  PASS  " : "  FAIL  ") + msg); if (!c) fails++; };

// deterministic noise
let seed = 12345; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
const gauss = () => (rnd() + rnd() + rnd() + rnd() - 2) * 1.7;

// the user's pitch (cents vs 110 Hz) at content-time tc, interpolating the reference contour
function refAt(f, tc) {
  const x = tc / L.H, i = Math.floor(x); if (i < 0 || i >= f.length) return null;
  const a = f[i], b = f[i + 1]; if (a == null) return null;
  return b == null ? a : a + (b - a) * (x - i);
}

// Simulate one attempt. userSpeed = how slowly the person really recites (content plays at this rate).
// appSpeed  = the speed the app assumes. "new" app: appSpeed == userSpeed. "legacy": appSpeed = 1.
function simulate(g, { userSpeed, appSpeed, transpose = 0, lag = 0.1, wobble = 18, rel = true, synth = false }) {
  const T = g.d, Q = L.newQ(), dt = 1 / 60, sr = 44100, buf = new Float32Array(2048);
  let phase = 0;
  for (let t = 0; ; t += dt) {
    const tc = t * appSpeed;                    // what the app thinks the content time is
    if (tc > T + 0.4) break;
    const tu = (t - lag) * userSpeed;           // where the reciter really is in the ayah
    const c = tu < 0 ? null : refAt(g.f, tu);
    let hz = 0;
    if (c != null) hz = 110 * 2 ** ((c + transpose + gauss() * wobble) / 1200);
    let f;
    if (synth && hz > 0) {                      // real audio through the real YIN
      const w = 2 * Math.PI * hz / sr; for (let i = 0; i < buf.length; i++) { buf[i] = 0.3 * Math.sin(phase); phase += w; }
      f = L.yin(buf, sr);
    } else f = hz;
    L.stepRec(Q, g.f, tc, f, rel);
  }
  return L.scoreOf(Q);
}

const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const segs = quran.flatMap(r => r.segs.map(s => ({ s, id: r.id })));
// transposition that moves each contour near a comfortable male voice (~150 Hz) to stay inside YIN's range
const shiftFor = g => { const v = g.f.filter(x => x != null).sort((a, b) => a - b); return 1200 * Math.log2(150 / 110) - v[v.length >> 1]; };

console.log(`\nSpeed-adjusted scoring, ${segs.length} ayat from ${quran.length} riwayat (pitch fed directly, 0.1 s late start, ±18 cent wobble, transposed)\n`);
console.log("  speed | app timeline      | mean score | min");
const res = {};
for (const sp of [1, 0.75, 0.5]) for (const mode of ["new", "legacy"]) {
  if (sp == 1 && mode == "legacy") continue;
  const sc = segs.map(({ s }) => simulate(s, { userSpeed: sp, appSpeed: mode == "new" ? sp : 1, transpose: shiftFor(s) }));
  res[sp + mode] = mean(sc);
  console.log(`  ${String(sp).padEnd(5)} | ${(mode == "new" ? "scaled (this build)" : "unscaled (old build)").padEnd(17)} | ${mean(sc).toFixed(1).padStart(9)}% | ${Math.min(...sc)}%`);
}

// Observation: the scorer tolerates +-0.2 s of *content* time. Slower speed makes the same real-world
// reaction delay smaller in content time, so it is also more forgiving of a late start.
console.log("\nLate-start sensitivity (mean score, scaled timeline):");
console.log("  late start | 1x     | 0.75x  | 0.5x");
for (const lag of [0.1, 0.25, 0.4]) {
  const row = [1, 0.75, 0.5].map(sp => mean(segs.map(({ s }) => simulate(s, { userSpeed: sp, appSpeed: sp, lag, transpose: shiftFor(s) }))));
  console.log(`  ${(lag + " s").padEnd(10)} | ${row.map(v => (v.toFixed(1) + "%").padEnd(6)).join(" | ")}`);
}

console.log("\nAssertions:");
ok(res["1new"] >= 85, `1x baseline scores well (${res["1new"].toFixed(1)}%)`);
ok(res["0.75new"] >= res["1new"] - 4, `0.75x scores like 1x (${res["0.75new"].toFixed(1)}% vs ${res["1new"].toFixed(1)}%)`);
ok(res["0.5new"] >= res["1new"] - 4, `0.5x scores like 1x (${res["0.5new"].toFixed(1)}% vs ${res["1new"].toFixed(1)}%)`);
ok(res["0.5legacy"] < 60, `without the fix a 0.5x recitation is unfairly marked down (${res["0.5legacy"].toFixed(1)}%)`);
ok(res["0.5new"] - res["0.5legacy"] > 25, `the fix recovers ${(res["0.5new"] - res["0.5legacy"]).toFixed(0)} points at 0.5x`);

// a genuinely wrong recitation must still score low at every speed (the fix must not make scoring lenient)
for (const sp of [1, 0.5]) {
  const bad = segs.map(({ s }, k) => simulate(s, { userSpeed: sp, appSpeed: sp, transpose: shiftFor(s) }) &&
    // wrong melody: reciting a different ayah's contour against this one
    (() => { const other = segs[(k + 9) % segs.length].s; const g2 = { ...s, f: other.f.slice(0, s.f.length) };
      const Q = L.newQ(); const T = s.d; let seedLocal = 0;
      for (let t = 0; ; t += 1 / 60) { const tc = t * sp; if (tc > T + .4) break; const c = refAt(g2.f, (t - .1) * sp);
        const hz = c == null ? 0 : 110 * 2 ** ((c + shiftFor(g2)) / 1200); L.stepRec(Q, s.f, tc, hz, true); }
      return L.scoreOf(Q); })());
  ok(mean(bad) < mean([res["1new"]]) - 15, `wrong melody still scores clearly lower at ${sp}x (${mean(bad).toFixed(1)}%)`);
}

// real audio through the real YIN, on a subset (slower)
console.log("\nEnd-to-end with synthesized audio + real YIN (subset):");
const sub = segs.filter((_, i) => i % 4 == 0);
const e2e = {};
for (const sp of [1, 0.5]) {
  e2e[sp] = mean(sub.map(({ s }) => simulate(s, { userSpeed: sp, appSpeed: sp, transpose: shiftFor(s), synth: true })));
  console.log(`  ${sp}x -> ${e2e[sp].toFixed(1)}%`);
}
ok(e2e[0.5] >= e2e[1] - 6, `with real YIN, 0.5x stays within 6 points of 1x (${e2e[0.5].toFixed(1)}% vs ${e2e[1].toFixed(1)}%)`);
ok(e2e[0.5] >= 80, `with real YIN, 0.5x scores >= 80% (${e2e[0.5].toFixed(1)}%)`);

// YIN sanity
const sr = 44100, b = new Float32Array(2048); for (let i = 0; i < 2048; i++) b[i] = .3 * Math.sin(2 * Math.PI * 220 * i / sr);
ok(Math.abs(L.yin(b, sr) - 220) < 1.5, `YIN detects a 220 Hz tone (${L.yin(b, sr).toFixed(1)} Hz)`);

console.log(fails ? `\n${fails} FAILED` : "\nAll passed");
process.exit(fails ? 1 : 0);
