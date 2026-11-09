#!/usr/bin/env python3
"""Cut Fajr adhan recordings into 14 phrase segments and extract pitch contours.

Usage:  python segment.py <input_dir> <output_dir> [recording_id ...]
Needs:  ffmpeg, numpy, scipy (librosa and soundfile are optional accelerators)
Output: <output_dir>/<id>/01.mp3 ... 14.mp3  and  <output_dir>/recordings.json
Method: loudness-based phrase detection (no speech recognition). Each recording
        is cut into 14 phrases unless a recording explicitly changes the expected count.
Notes:  * Recordings whose source file is not in <input_dir> are kept as they already are in
          <output_dir>/recordings.json, so you can add new recordings without the old sources.
        * A recording may carry tuning options (last tuple item): "bridge" (seconds of pause that
          still count as one phrase), "off" (dB added to the loudness threshold), "split" (times in
          seconds where one detected block is really two phrases) and "merge" (groups of block
          numbers, counted after splitting, that are really one phrase), "drop" (0-based block
          numbers to omit after splitting/merging), "expect" (resulting phrase count),
          and "ton" (tonic in cents, overriding the automatic estimate when the call does not
          close on the tonic).
"""
import json, os, subprocess, sys, tempfile, wave
import numpy as np
try:
    import soundfile as sf
except ImportError:
    sf = None
try:
    import librosa
except ImportError:
    librosa = None
from scipy.signal import medfilt

NAME_TBD = "مؤذن (الاسم لم يُضَف بعد)"
# id, file name, display name, note, maqam key (None = not confirmed), [tuning options]
RECORDINGS = [
    ("asaba", "azan-saba-2014-al-fajr.mp3", "مشاري راشد العفاسي", "أذان الفجر (صبا)", "saba"),
    ("a40", "404627.mp3", "الشيخ عبد الباسط عبد الصمد", "أذان الفجر 1 — إسلام ويب", "rast"),
    ("a18", "018-.mp3", "أذان الحرم المدني", "الأذان بعدة أصوات ندية", "bayati"),   # least certain: please confirm by ear
    ("a20", "020--2.mp3", "أذان الحرم المكي", "الأذان بعدة أصوات ندية", "hijaz"),
    # added later. Maqam identified from the pitch analysis of each recording; reciter names still to be filled in
    ("nahawand", "nahawand.mp3", NAME_TBD, "أذان الفجر", "nahawand",
     {"bridge": 0.45, "split": [152.5], "merge": [[0, 1], [2, 3], [14, 15]]}),  # 4 opening + 2 closing takbir calls, 2 khayr phrases joined
    ("sikah", "sikah.mp3", NAME_TBD, "أذان الفجر", "sikah", {"ton": 0}),      # held-note centre; auto estimate drifted to 1149
    ("ajam", "ajam.mp3", NAME_TBD, "أذان الفجر", "ajam", {"ton": 993}),     # same notes as Kurd; tonic = long closing hold (auto estimate picked the 3rd)
    ("kurd", "kurd.mp3", NAME_TBD, "أذان الفجر", "kurd", {"bridge": 0.4, "off": 3}),
    ("adnan", "adnan el halaq.mp3", "عدنان الحلاق", "أذان الفجر", "sikah",
     {"bridge": 0.1, "off": 6, "split": [240]}),
    ("hesham", "hesham elsqaf.mp3", "هاشم السقاف", "أذان الفجر", "bayati", {"off": -3}),
    ("nasr", "nasr elqtamy.mp3", "ناصر القطامي", "أذان الفجر", "hijaz",
     {"bridge": 0.6, "drop": [11, 13], "expect": 14}),
]
REF_HZ = 110.0  # cents are measured relative to A2 = 110 Hz


def phrase_blocks(db, step=0.05, bridge=0.6, off=0.0, minlen=3):
    """Return [start, end] seconds of loud blocks, using an adaptive threshold."""
    thr = (np.percentile(db, 85) + np.percentile(db, 15)) / 2
    for _ in range(10):
        thr = (db[db > thr].mean() + db[db <= thr].mean()) / 2
    thr += off
    blocks, s = [], None
    for i, loud in enumerate(db > thr):
        if loud and s is None:
            s = i
        if (not loud or i == len(db) - 1) and s is not None:
            if blocks and (s - blocks[-1][1]) * step < bridge:   # bridge short pauses (default 0.6 s)
                blocks[-1][1] = i
            else:
                blocks.append([s, i])
            s = None
    blocks = [[a * step, b * step] for a, b in blocks]
    while True:                                               # merge fragments < minlen s
        tiny = [i for i, (a, b) in enumerate(blocks) if b - a < minlen]
        if not tiny:
            return blocks
        i = tiny[0]
        if i + 1 < len(blocks) and (i == 0 or blocks[i + 1][0] - blocks[i][1] < blocks[i][0] - blocks[i - 1][1]):
            blocks[i + 1][0] = blocks[i][0]
        elif i > 0:
            blocks[i - 1][1] = blocks[i][1]
        blocks.pop(i)


def pitch_contour(y, sr):
    """F0 in cents (re 110 Hz), 40 ms hop, None where unvoiced, octave jumps removed."""
    if librosa is not None:
        f0, _, _ = librosa.pyin(y, fmin=65, fmax=700, sr=sr, frame_length=1024, hop_length=320)
    else:
        f0 = yin_f0(y, sr, frame_length=1024, hop_length=320, fmin=65, fmax=700)
    c = 1200 * np.log2(f0 / REF_HZ)
    ok = ~np.isnan(c)
    if ok.sum() > 5:
        c[ok] = medfilt(c[ok], 5)
        prev = None
        for i in np.where(ok)[0]:
            if prev is not None:
                while c[i] - prev > 600: c[i] -= 1200
                while c[i] - prev < -600: c[i] += 1200
            prev = c[i]
    return [None if np.isnan(x) else int(round(x)) for x in c[::2]]


def yin_f0(y, sr, frame_length=1024, hop_length=320, fmin=65, fmax=700):
    """YIN pitch fallback for installs without librosa; returns Hz or NaN per frame."""
    y = np.asarray(y, dtype=np.float32)
    if not len(y):
        return np.array([], dtype=float)
    half = frame_length // 2
    y = np.pad(y, (half, half), mode="reflect") if len(y) > 1 else np.pad(y, (half, half))
    count = 1 + (len(y) - frame_length) // hop_length
    min_lag = max(2, int(sr / fmax))
    max_lag = min(frame_length - 2, int(sr / fmin))
    lags = np.arange(1, max_lag + 1)
    window = np.hanning(frame_length).astype(np.float32)
    nfft = 1 << (2 * frame_length - 1).bit_length()
    result = np.full(count, np.nan, dtype=float)
    for i in range(count):
        frame = y[i * hop_length:i * hop_length + frame_length]
        if np.sqrt(np.mean(frame * frame)) < 0.008:
            continue
        frame = (frame - np.mean(frame)) * window
        spec = np.fft.rfft(frame, nfft)
        acf = np.fft.irfft(spec * np.conjugate(spec), nfft)[:max_lag + 1]
        energy = np.concatenate(([0.0], np.cumsum(frame * frame)))
        left = energy[frame_length - lags]
        right = energy[-1] - energy[lags]
        diff = np.maximum(0, left + right - 2 * acf[lags])
        cmnd = diff * lags / np.maximum(np.cumsum(diff), 1e-12)
        valid = cmnd[min_lag - 1:]
        if not len(valid):
            continue
        below = np.flatnonzero(valid < 0.15)
        idx = min_lag - 1 + (int(below[0]) if len(below) else int(np.argmin(valid)))
        while idx + 1 < len(cmnd) and cmnd[idx + 1] < cmnd[idx]:
            idx += 1
        if cmnd[idx] > 0.4:
            continue
        lag = float(idx + 1)
        if 0 < idx < len(cmnd) - 1:
            a, b, c = cmnd[idx - 1:idx + 2]
            denom = a - 2 * b + c
            if abs(denom) > 1e-12:
                lag += 0.5 * (a - c) / denom
        result[i] = sr / lag
    return result


def read_wav(path):
    """Read the mono PCM WAV produced by ffmpeg, with soundfile as an optional fast path."""
    if sf is not None:
        return sf.read(path)
    with wave.open(path, "rb") as wav:
        sr, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"Expected 16-bit PCM WAV from ffmpeg, got {width * 8}-bit")
    y = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        y = y.reshape(-1, channels).mean(axis=1)
    return y, sr


def tonic_cents(segs):
    """Tonic estimate = median held note at the end of phrases 4, 6, 8, 10 and 14 (mod one octave).
    These phrases close on the tonic; using all of them, not just the last, stops a singer's
    upward pitch drift over the call (up to ~70 cents in a18) from skewing the estimate."""
    ends = []
    for k in sorted(set((3, 5, 7, 9, len(segs) - 1))):
        if k < 0 or k >= len(segs):
            continue
        v = [x for x in segs[k]["f"] if x is not None][-60:-12]
        if v:
            ends.append(np.median(v))
    ref = ends[-1]
    return int(round(ref + np.median([((e - ref + 600) % 1200) - 600 for e in ends])) % 1200)


def adjust_blocks(blocks, split=(), merge=()):
    """Apply manual fixes: split blocks at given times, then merge groups of block numbers (0-based)."""
    for t in sorted(split):
        for k, (a, b) in enumerate(blocks):
            if a < t < b:
                blocks[k:k + 1] = [[a, t - 0.1], [t + 0.1, b]]
                break
    drop = set()
    for grp in merge:
        blocks[grp[0]][1] = blocks[grp[-1]][1]
        drop.update(grp[1:])
    return [b for k, b in enumerate(blocks) if k not in drop]


def main(src_dir, out_dir, only_ids=None):
    os.makedirs(out_dir, exist_ok=True)
    jpath = os.path.join(out_dir, "recordings.json")
    old = {r["id"]: r for r in json.load(open(jpath, encoding="utf-8"))} if os.path.exists(jpath) else {}
    if only_ids is not None:
        only_ids = set(only_ids)
        unknown = only_ids - {r[0] for r in RECORDINGS}
        if unknown:
            sys.exit("Unknown recording id(s): " + ", ".join(sorted(unknown)))
    result = []
    for rec in RECORDINGS:
        rid, fname, name, note, maqam = rec[:5]
        if only_ids is not None and rid not in only_ids:
            if rid in old:
                result.append(old[rid])
            continue
        opts = rec[5] if len(rec) > 5 else {}
        src = os.path.join(src_dir, fname)
        if not os.path.exists(src):
            if rid in old:                      # source not available: keep what is already cut
                old[rid].update({"n": name, "t": note, "mq": maqam})
                result.append(old[rid])
                print(rid, "kept (no source file)")
                continue
            sys.exit(f"{fname}: not found in {src_dir}")
        wav = os.path.join(tempfile.gettempdir(), rid + ".wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", wav], check=True)
        y, sr = read_wav(wav)
        h = int(0.05 * sr)
        db = 20 * np.log10(np.array([np.sqrt(np.mean(y[i:i + h] ** 2)) for i in range(0, len(y) - h, h)]) + 1e-5)
        blocks = phrase_blocks(db, bridge=opts.get("bridge", 0.6), off=opts.get("off", 0.0))
        blocks = adjust_blocks(blocks, opts.get("split", ()), opts.get("merge", ()))
        drop = set(opts.get("drop", ()))
        if any(k < 0 or k >= len(blocks) for k in drop):
            sys.exit(f"{fname}: drop index outside detected phrase blocks")
        blocks = [b for k, b in enumerate(blocks) if k not in drop]
        expected = opts.get("expect", 14)
        if len(blocks) != expected:
            sys.exit(f"{fname}: found {len(blocks)} phrases, expected {expected}")
        os.makedirs(os.path.join(out_dir, rid), exist_ok=True)
        segs, total = [], len(y) / sr
        for k, (a, b) in enumerate(blocks):
            s = max(a - 0.15, (blocks[k - 1][1] + a) / 2 if k else 0)          # 0.15 s pre-roll
            e = min(b + 0.45, (blocks[k + 1][0] + b) / 2 if k < len(blocks) - 1 else total)  # 0.45 s tail
            rel = f"{rid}/{k + 1:02d}.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", src,
                            "-ac", "1", "-ar", "22050", "-b:a", "40k", os.path.join(out_dir, rel)], check=True)
            segs.append({"a": "data/" + rel, "d": round(e - s, 2), "start": round(s, 2), "end": round(e, 2),
                         "f": pitch_contour(y[int(s * sr):int(e * sr)].astype(np.float32), sr)})
        for stale in range(len(segs) + 1, 15):
            path = os.path.join(out_dir, rid, f"{stale:02d}.mp3")
            if os.path.exists(path):
                os.remove(path)
        result.append({"id": rid, "n": name, "t": note, "mq": maqam, "ton": opts.get("ton", tonic_cents(segs)), "segs": segs})
        print(rid, [x["d"] for x in segs])
    json.dump(result, open(jpath, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        main(sys.argv[1], sys.argv[2], sys.argv[3:] or None)
    else:
        main("uploads", "data")
