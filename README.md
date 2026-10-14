# صدى (Sada) - learn the adhan and the Quran by imitation

Two features in one site:

* **Adhan** (`#/studio`): eight maqams, one recording each, 14 phrases per adhan.
* **Quran** (`#/quran`): Surat Al-Fatiha in four riwayat (Qalun 'an Nafi', Hafs 'an 'Asim, Warsh 'an Nafi', Al-Duri 'an Abi 'Amr al-Basri), 7 ayat per recording.

Quran recordings (all by Al-Husary, from mp3quran.net): `qalun`, `hafs`, `warsh`, `duri`, each cut into 7 ayat
(basmala = ayah 1, ayah 7 = "صراط الذين ... ولا الضالين"). Source names expected by `segment_quran.py`:
qalun.mp3, hafs.mp3, warsh.mp3, duri.mp3.

The site name is in `index.html` (title tag and the `<nav>` line).

## Adhan Run locally (the page loads data/recordings.json, so it needs a web server):

    cd fajr-project && python3 -m http.server 8000   # open http://localhost:8000

## Recordings

| Maqam | Reciter | id |
|---|---|---|
| Bayati (البياتي) | أذان الحرم المدني | a18 |
| Saba (الصبا) | مشاري راشد العفاسي | asaba |
| Rast (الرست) | الشيخ عبد الباسط عبد الصمد | a40 |
| Hijaz (الحجاز) | أذان الحرم المكي | a20 |
| Nahawand (النهاوند) | *name to be added* | nahawand |
| Sikah (السيكا) | *name to be added* | sikah |
| Ajam (العجم) | *name to be added* | ajam |
| Kurd (الكرد) | *name to be added* | kurd |

The last four were classified from pitch analysis of the recordings (held-note scale degrees and where the call closes).
Ajam and Kurd share the same notes and differ only in which note is the tonic, so Ajam is the one to double-check by ear.

## Filling in a reciter name

Edit `NAME_TBD` / the name field in `segment.py` (RECORDINGS) and in `data/recordings.json` (the `"n"` value of that recording).

## Re-cutting

Needs ffmpeg + `pip install numpy scipy librosa soundfile`:

    python3 segment.py /path/to/mp3s data

Recordings whose source mp3 is not in that folder are kept as they are in data/recordings.json, so you can add new ones
without the old sources. Expected source names for the new four: nahawand.mp3, sikah.mp3, ajam.mp3, kurd.mp3.
Per-recording tuning options (pause bridging, manual split/merge of phrases, tonic override) are documented at the top of segment.py.

## Adding or replacing Quran recordings

1. Put the four recitation files in one folder, for example `hafs.mp3`, `warsh.mp3`, `qalun.mp3`, `duri.mp3`.
2. In `segment_quran.py` fill in `RECORDINGS` (id, file name, riwaya key `qalun | hafs | warsh | duri`, reciter, the 7 texts).
   The texts differ between riwayat (for example Hafs reads مَٰلِكِ, Warsh / Qalun / Al-Duri read مَلِكِ), so each recording carries its own.
3. Run `python3 segment_quran.py /path/to/mp3s data`. It cuts 7 ayat per recording into `data/<id>/01.mp3 ... 07.mp3`,
   extracts the pitch contours and writes `data/quran.json`. If the number of detected pauses is not 7 it stops and prints
   the detected blocks, and you can tune `bridge`, `off`, `minlen`, `split`, `merge` or `skip_start` for that recording.
4. Reload the page: the riwaya cards unlock.

The Quran studio compares pitch and rhythm only. It does not check tajweed or pronunciation.

## Playback / recording speed (1x, 0.75x, 0.5x)

Both studios have a speed selector above the pitch graph. It slows the reference audio **without changing its pitch**
(`preservesPitch`) and stretches the recording timeline by the same factor, so a slow recitation is compared with the
matching moment of the reference instead of a fast one. The choice is remembered between visits.
While listening, a playhead moves across the graph so you can follow along.

Internally the scorer works in "content time" (real seconds x speed). The scoring code sits between the
`PURE-START` / `PURE-END` markers in `index.html` and is tested with a simulation:

    node test/speed-sim.js

The test simulates a reciter at 1x / 0.75x / 0.5x over all Quran ayat, checks that scores stay level across speeds,
that a wrong melody still scores low, and that the old unscaled timeline would have scored a 0.5x recitation about 40 points lower.

## Progress history

Every attempt that runs to the end of the ayah/phrase is saved in the browser (`localStorage`, key `sada.hist`):
date, recording, ayah/phrase number, speed and score. Nothing is sent to a server. Stopping a recording early is **not** saved.
Below the analysis studio (section 5) you get: attempts, average of the last 10, best score, days practiced,
the best score and attempt count for every ayah of the selected recording (tap a row to practice it),
a trend curve with the 85% line, and the last 8 attempts. "Clear" only deletes the history of the current page (Adhan or Quran).
The history is capped at the latest 500 attempts. It is per browser and per device (clearing site data deletes it).
The history logic is covered by `node test/speed-sim.js`.

