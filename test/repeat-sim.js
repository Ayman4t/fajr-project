// Simulated test for the repeat-listening feature (adhan + Quran studios share it).
// Run:  node test/repeat-sim.js
// It loads the REAL inline script from index.html inside a vm with a fake Audio, fake timers and a fake DOM,
// then drives listen() / setRp() / stopListen() the way the buttons do.
const fs = require("fs"), path = require("path"), vm = require("vm");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error("inline script not found in index.html");
// drop the bootstrap line (hashchange listeners + data fetch); everything above it is loaded as is
const cut = m[1].indexOf('addEventListener("hashchange"');
if (cut < 0) throw new Error("bootstrap line not found");
const code = m[1].slice(0, cut);

const rpnEl = { textContent: "" };
const store = {};
const timers = [];
class FakeAudio {
  constructor(src) { this.src = src; this.paused = true; this.ended = false; this.currentTime = 0; FakeAudio.all.push(this); }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  finish() { this.paused = true; this.ended = true; this.onended && this.onended(); }
}
FakeAudio.all = [];
const sandbox = {
  console, Audio: FakeAudio,
  document: { getElementById: id => (id === "rpn" ? rpnEl : null), querySelectorAll: () => [] },
  localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  location: { hash: "#/quran" },
  setTimeout: (fn, ms) => { const t = { fn, ms, live: true }; timers.push(t); return t; },
  requestAnimationFrame: () => 0,
  performance: { now: () => 0 },
  devicePixelRatio: 1,
};
sandbox.window = sandbox;

const test = `
let fails = 0;
const ok = (c, msg) => { console.log((c ? "  PASS  " : "  FAIL  ") + msg); if (!c) fails++; };
const audios = () => Audio.all;
const pending = () => __timers.filter(t => t.live);
const fire = () => { const t = pending()[0]; if (!t) return false; t.live = false; t.fn(); return true; };
const reset = () => { Audio.all.length = 0; __timers.length = 0; stopA(); rpNote(""); };

QREC = [{ id: "hafs", rw: "hafs", segs: [{ a: "data/hafs/01.mp3", d: 5, f: [0, 0] }] }];
S.r = "hafs"; S.i = 0;

console.log("repeat = 1 (default behaviour is unchanged)");
ok(S.rp === 1, "default repeat is once");
reset(); listen();
ok(audios().length === 1 && audios()[0].src === "data/hafs/01.mp3", "listen() plays the selected ayah once");
audios()[0].finish();
ok(pending().length === 0 && audios().length === 1, "no repeat is scheduled when repeat = 1");

console.log("repeat = 3");
setRp(3); ok(__store["sada.rp"] === "3", "choice is remembered in localStorage");
reset(); listen();
ok(__rpn.textContent === "تكرار 1 من 3", "counter shows 1 of 3 (" + __rpn.textContent + ")");
audios()[0].finish();
ok(pending().length === 1 && pending()[0].ms === RPGAP, "a " + RPGAP + "ms pause is scheduled after the first play");
fire();
ok(audios().length === 2 && __rpn.textContent === "تكرار 2 من 3", "second play starts, counter shows 2 of 3");
audios()[1].finish(); fire();
ok(audios().length === 3 && __rpn.textContent === "تكرار 3 من 3", "third play starts, counter shows 3 of 3");
audios()[2].finish();
ok(pending().length === 0 && audios().length === 3 && __rpn.textContent === "", "stops after exactly 3 plays and clears the counter");

console.log("repeat = infinite");
setRp(0); reset(); listen();
for (let k = 0; k < 8; k++) { audios()[audios().length - 1].finish(); fire(); }
ok(audios().length === 9, "keeps going well past 5 plays (" + audios().length + " so far)");
audios()[audios().length - 1].finish();
ok(pending().length === 1, "a repeat is waiting in the pause");
stopListen();
fire();
ok(audios().length === 9 && __rpn.textContent === "", "stop during the pause cancels the next repeat and clears the counter");

console.log("stopping and switching");
setRp(0); reset(); listen();
const a1 = audios()[0];
stopListen(); a1.finish();
ok(audios().length === 1 && pending().length === 0, "stop during playback prevents any repeat");
reset(); listen(); audios()[0].finish(); fire();
setRp(1); audios()[1].finish();
ok(pending().length === 0 && audios().length === 2, "switching to 1x mid-loop ends the loop after the current play");
setRp(3); reset(); listen(); audios()[0].finish();
const old = audios()[0]; listen();
old.finish();
ok(audios().length === 2 && pending().length === 1 && pending()[0].live, "starting a new listen() restarts the count and ignores the old audio");
ok(__rpn.textContent === "تكرار 1 من 3", "counter restarted at 1");
fire(); ok(audios().length === 2, "the stale pause from the old loop does not start an extra play");

console.log("recording");
setRp(5); reset(); listen(); audios()[0].finish();
rec = {}; fire();
ok(audios().length === 1, "no repeat starts while a recording is running");
rec = null;

__result.fails = fails;
`;

const ctx = vm.createContext(sandbox);
sandbox.__timers = timers; sandbox.__store = store; sandbox.__rpn = rpnEl; sandbox.__result = { fails: 0 };
vm.runInContext(code + "\n" + test, ctx);
if (sandbox.__result.fails) { console.log("\n" + sandbox.__result.fails + " FAILED"); process.exit(1); }
console.log("\nAll passed");
