#!/usr/bin/env python3
"""Cut Surat Al-Fatiha recordings into 7 ayat and extract pitch contours.

Usage:  python3 segment_quran.py <input_dir> <output_dir>        (output_dir is normally "data")
Needs:  ffmpeg, numpy, scipy, librosa, soundfile  (same as segment.py)
Output: <output_dir>/<id>/01.mp3 ... 07.mp3  and  <output_dir>/quran.json

Method: same loudness-based pause detection as segment.py (no speech recognition). Each recording must
        contain exactly as many pause-separated blocks as it has texts (7). If the count is different the
        script stops and prints the detected blocks (start-end seconds) so you can tune the options:
        "bridge" / "off" / "minlen"  - pause detection (see segment.py)
        "split" / "merge"            - manual fixes (see segment.py)
        "skip_start"                 - seconds to ignore at the start (e.g. an audible isti'adha before the recitation)
Notes:  * Recordings whose source file is not in <input_dir> are kept as they already are in quran.json.
        * Each recording carries its own 7 texts, because the text differs between riwayat
          (for example Hafs reads مَٰلِكِ and Warsh / Qalun / Al-Duri read مَلِكِ).
"""
import json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf
from segment import phrase_blocks, adjust_blocks, pitch_contour

RECITER = "الشيخ محمود خليل الحصري"
NOTE = "سورة الفاتحة"

# The seven ayat as given for Hafs 'an 'Asim (basmala counted as ayah 1).
TEXT_HAFS = [
    "بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ",
    "ٱلۡحَمۡدُ لِلَّهِ رَبِّ ٱلۡعَٰلَمِينَ",
    "ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ",
    "مَٰلِكِ يَوۡمِ ٱلدِّينِ",
    "إِيَّاكَ نَعۡبُدُ وَإِيَّاكَ نَسۡتَعِينُ",
    "ٱهۡدِنَا ٱلصِّرَٰطَ ٱلۡمُسۡتَقِيمَ",
    "صِرَٰطَ ٱلَّذِينَ أَنۡعَمۡتَ عَلَيۡهِمۡ غَيۡرِ ٱلۡمَغۡضُوبِ عَلَيۡهِمۡ وَلَا ٱلضَّآلِّينَ",
]

# id, source file name, riwaya key (qalun | hafs | warsh | duri), reciter, texts, [tuning options]
RECORDINGS = [
    # Filled in once the four real recitation recordings are available, for example:
    # ("hafs", "hafs.mp3", "hafs", RECITER, TEXT_HAFS),
    # ("warsh", "warsh.mp3", "warsh", RECITER, TEXT_WARSH, {"bridge": 0.5}),
]


def main(src_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    jpath = os.path.join(out_dir, "quran.json")
    old = {r["id"]: r for r in json.load(open(jpath, encoding="utf-8"))} if os.path.exists(jpath) else {}
    result = []
    for rec in RECORDINGS:
        rid, fname, rw, reciter, texts = rec[:5]
        opts = rec[5] if len(rec) > 5 else {}
        src = os.path.join(src_dir, fname)
        if not os.path.exists(src):
            if rid in old:
                old[rid].update({"rw": rw, "n": reciter, "t": NOTE, "txt": texts})
                result.append(old[rid])
                print(rid, "kept (no source file)")
                continue
            sys.exit(f"{fname}: not found in {src_dir}")
        wav = os.path.join(tempfile.gettempdir(), "q_" + rid + ".wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", wav], check=True)
        y, sr = sf.read(wav)
        h = int(0.05 * sr)
        db = 20 * np.log10(np.array([np.sqrt(np.mean(y[i:i + h] ** 2)) for i in range(0, len(y) - h, h)]) + 1e-5)
        blocks = phrase_blocks(db, bridge=opts.get("bridge", 0.6), off=opts.get("off", 0.0), minlen=opts.get("minlen", 1.5))
        blocks = [b for b in blocks if b[1] > opts.get("skip_start", 0)]
        blocks = adjust_blocks(blocks, opts.get("split", ()), opts.get("merge", ()))
        n = len(texts)
        if len(blocks) != n:
            print(f"{fname}: found {len(blocks)} blocks, expected {n}. Detected (start-end s):")
            print("  " + "  ".join(f"{a:.1f}-{b:.1f}" for a, b in blocks))
            sys.exit("Adjust the options for this recording (bridge / off / minlen / split / merge / skip_start).")
        os.makedirs(os.path.join(out_dir, rid), exist_ok=True)
        segs, total = [], len(y) / sr
        for k, (a, b) in enumerate(blocks):
            s = max(a - 0.15, (blocks[k - 1][1] + a) / 2 if k else 0)
            e = min(b + 0.45, (blocks[k + 1][0] + b) / 2 if k < n - 1 else total)
            rel = f"{rid}/{k + 1:02d}.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", src,
                            "-ac", "1", "-ar", "22050", "-b:a", "40k", os.path.join(out_dir, rel)], check=True)
            segs.append({"a": "data/" + rel, "d": round(e - s, 2), "start": round(s, 2), "end": round(e, 2),
                         "f": pitch_contour(y[int(s * sr):int(e * sr)].astype(np.float32), sr)})
        result.append({"id": rid, "rw": rw, "n": reciter, "t": NOTE, "txt": texts, "segs": segs})
        print(rid, [x["d"] for x in segs])
    json.dump(result, open(jpath, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main(*(sys.argv[1:3] if len(sys.argv) >= 3 else ("uploads", "data")))
