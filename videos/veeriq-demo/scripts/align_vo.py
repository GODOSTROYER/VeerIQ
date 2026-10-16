"""Cut the narration chunks into lines at the real word boundaries, and record word timings.

tts.py --chunked voices each act group in one request (the free tier allows 10 TTS requests per model per
day) and saves assets/vo/_chunk-<group>.wav. This script transcribes each chunk with the HyperFrames CLI
(whisper, word timestamps), aligns the transcript to the script words of that group, and cuts each line
in the real pause between the last word of one line and the first word of the next (whisper's word times
alone can land a cut inside a word). Gemini's audio starts with a full-scale click and ends with ~120 ms of
full-scale noise, so both are cut off, and every line gets a short fade in and out. It writes:
  assets/vo/<id>.wav          one line each
  assets/vo/durations.json    line durations (s)
  assets/vo/words.json        per line: [[word, start, end], ...] relative to the line's own start, from
                              transcribing each cut line on its own (chunk-level word times run early
                              around pauses, so they are only used to find the cuts)

  python scripts/align_vo.py
"""
import difflib
import json
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VO = ROOT / "assets" / "vo"


def norm(w):
    w = w.lower().replace("’", "'")
    w = re.sub(r"[^a-z0-9']", "", w)
    return {"veeriq": "vriq", "veeriqs": "vriqs", "two": "2"}.get(w, w)


def transcribe(wav):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["npx", "--yes", "hyperframes@0.8.158", "transcribe", str(wav), "-d", d, "--model", "base.en", "--json"],
                       check=True, capture_output=True)
        data = json.loads((Path(d) / "transcript.json").read_text())
    words = data if isinstance(data, list) else (data.get("words") or [])
    return [((x.get("text") or x.get("word") or "").strip(), float(x["start"]), float(x["end"])) for x in words]


def pauses(wav):
    """Pauses (start, end) of at least 120 ms below -40 dB, and the chunk's last clean sample time."""
    import wave, array
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = array.array("h", w.readframes(w.getnframes()))
    hop, win = sr // 100, sr * 3 // 100
    db = []
    for i in range(0, len(x) - win, hop):
        seg = x[i:i + win:4]
        ms = sum(v * v for v in seg) / len(seg) / 32768.0 ** 2
        db.append(10 * __import__("math").log10(ms + 1e-12))
    out, i = [], 0
    while i < len(db):
        if db[i] < -40:
            j = i
            while j < len(db) and db[j] < -40:
                j += 1
            if j - i >= 12:
                out.append((i / 100, j / 100))
            i = j
        else:
            i += 1
    total = len(x) / sr
    # The noise burst follows the final pause: end the chunk just after that pause starts.
    tail = [q for q in out if q[0] > total - 1.2]
    end = tail[-1][0] + 0.08 if tail else total - 0.15
    return out, end


def snap(end_prev, start_next, cands):
    """Each line ends a sentence, so the cut goes in the middle of the longest real pause around the gap between
    the last word of one line and the first word of the next (whisper's word times are only roughly right)."""
    near = [q for q in cands if q[1] > end_prev - 0.4 and q[0] < start_next + 0.4]
    if not near:
        return (end_prev + start_next) / 2
    q = max(near, key=lambda q: q[1] - q[0])
    return (q[0] + q[1]) / 2


def duration(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]))


def main():
    lines = json.loads((ROOT / "scripts" / "narration.json").read_text())
    groups = {}
    for ln in lines:
        groups.setdefault(ln["group"], []).append(ln)
    durs, words_out = {}, {}
    for g, members in groups.items():
        chunk = VO / ("_chunk-" + g + ".wav")
        heard = transcribe(chunk)
        script = [(i, w) for i, m in enumerate(members) for w in m["text"].split()]
        sm = difflib.SequenceMatcher(a=[norm(w) for _, w in script], b=[norm(w) for w, _, _ in heard], autojunk=False)
        s2h = {}
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                s2h[blk.a + k] = blk.b + k
        gaps, total = pauses(chunk)
        # first script-word index of each line
        firsts = [next(j for j, (li, _) in enumerate(script) if li == i) for i in range(len(members))]
        cuts = [0.02]  # skip the click on the first sample
        for i in range(1, len(members)):
            a = firsts[i]
            nxt = next((s2h[j] for j in range(a, len(script)) if j in s2h), None)       # first heard word of line i
            prv = next((s2h[j] for j in range(a - 1, -1, -1) if j in s2h), None)       # last heard word of line i-1
            if nxt is None or prv is None:
                raise SystemExit("could not align boundary %d in chunk %s" % (i, g))
            cuts.append(snap(heard[prv][2], heard[nxt][1], gaps))
        cuts.append(total)
        for i, m in enumerate(members):
            a0, a1 = cuts[i], cuts[i + 1]
            out = VO / (m["id"] + ".wav")
            # trim the silence at both ends; words.json is timed from the cut line itself below
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(chunk), "-ss", "%.3f" % a0, "-to", "%.3f" % a1, "-af",
                            "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                            "afade=t=in:d=0.008,areverse,afade=t=in:d=0.04,areverse",
                            str(out)], check=True)
            durs[m["id"]] = round(duration(out), 3)
    ids = [ln["id"] for ln in lines]
    with ThreadPoolExecutor(4) as ex:
        for lid, mine in zip(ids, ex.map(lambda lid: transcribe(VO / (lid + ".wav")), ids)):
            words_out[lid] = [[w, round(s, 3), round(e, 3)] for w, s, e in mine]
            first = mine[0][0] if mine else "?"
            last = mine[-1][0] if mine else "?"
            print("%-5s %6.2fs  %s … %s" % (lid, durs[lid], first, last), flush=True)
    (VO / "durations.json").write_text(json.dumps(durs, indent=1) + "\n")
    (VO / "words.json").write_text(json.dumps(words_out, indent=1) + "\n")


if __name__ == "__main__":
    main()
