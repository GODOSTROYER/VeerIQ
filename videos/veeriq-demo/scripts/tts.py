"""Narration for the VeerIQ submission video, voiced with Gemini TTS.

Reads scripts/narration.json ([{"id": ..., "text": ...}]), calls the Gemini API with the key in the
repository's gitignored .env (GEMINI_API_KEY), and writes one 48 kHz mono WAV per line to assets/vo/,
plus assets/vo/durations.json. The key is never printed or written anywhere else.

  python scripts/tts.py                 # all lines
  python scripts/tts.py --only l02      # one line
  python scripts/tts.py --voice Charon --model gemini-3.8-flash-lite-tts
  python scripts/tts.py --chunked       # one request per act group, split back into lines at the pauses

The free tier allows 10 TTS requests per model per day, so --chunked voices the whole script in 4 requests.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT.parents[1] / ".env"
STYLE = ""  # Gemini reads a style prefix aloud; plain text gives the natural read.


def key():
    for line in ENV.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("GEMINI_API_KEY is not set in " + str(ENV))


def speak(text, voice, model, out_wav):
    body = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key()})
    # The free tier allows 3 requests per minute per model: on 429, wait the advertised retryDelay and retry.
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            if e.code != 429 or attempt == 7:
                sys.exit("TTS request failed: HTTP %s %s" % (e.code, msg[:300]))
            m = re.search(r'"retryDelay":\s*"(\d+)s"', msg)
            time.sleep(int(m.group(1)) + 3 if m else 25)
    part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(part["data"])
    rate = 24000
    for bit in part.get("mimeType", "").split(";"):
        if bit.strip().startswith("rate="):
            rate = int(bit.split("=")[1])
    raw = out_wav.with_suffix(".pcm")
    raw.write_bytes(pcm)
    # PCM s16le mono -> 48 kHz WAV, leading/trailing silence trimmed so scene timing is tight.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", str(raw),
                    "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                           "silenceremove=start_periods=1:start_threshold=-50dB,areverse",
                    "-ar", "48000", str(out_wav)], check=True)
    raw.unlink()
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(out_wav)]))


def split(whole, outs, words=None):
    """Cut one chunk into len(outs) lines. Each boundary goes to the pause nearest the point where it should fall
    by word count (narration pace is near constant), so long pauses inside a line are not mistaken for breaks."""
    n = len(outs)
    log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(whole), "-af", "silencedetect=n=-42dB:d=0.28", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
    total = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(whole)]))
    cands = list(zip(starts, ends))
    if words:
        acc, gaps, used = 0, [], set()
        for w in words[:-1]:
            acc += w
            want = total * acc / sum(words)
            best = min((g for g in cands if g not in used and (not gaps or g[0] > gaps[-1][1])),
                       key=lambda g: abs((g[0] + g[1]) / 2 - want) - 0.6 * (g[1] - g[0]))
            gaps.append(best); used.add(best)
    else:
        gaps = sorted(sorted(cands, key=lambda g: g[1] - g[0], reverse=True)[: n - 1])
    cuts = [0.0] + [(s + e) / 2 for s, e in gaps] + [total]
    durs = []
    for out, a0, a1 in zip(outs, cuts[:-1], cuts[1:]):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(whole), "-ss", "%.3f" % a0, "-to", "%.3f" % a1, "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse",
                        str(out)], check=True)
        durs.append(float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)])))
    if len(gaps) != n - 1:
        print("warning: found %d pauses for %d lines in %s" % (len(gaps), n, whole.name), flush=True)
    return durs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="Charon")
    ap.add_argument("--model", default="gemini-3.8-flash-lite-tts")
    ap.add_argument("--chunked", action="store_true")
    ap.add_argument("--resplit", action="store_true", help="with --chunked: reuse saved chunks, only re-cut them")
    ap.add_argument("--only")
    ap.add_argument("--text", help="voice this text instead of narration.json (for voice tests)")
    ap.add_argument("--out", help="output wav for --text")
    a = ap.parse_args()
    if a.text:
        print(round(speak(a.text, a.voice, a.model, Path(a.out)), 2))
        return
    lines = json.loads((ROOT / "scripts" / "narration.json").read_text())
    vo = ROOT / "assets" / "vo"
    vo.mkdir(parents=True, exist_ok=True)
    dpath = vo / "durations.json"
    durs = json.loads(dpath.read_text()) if dpath.exists() else {}
    if a.chunked:
        groups = {}
        for ln in lines:
            groups.setdefault(ln.get("group", ln["id"]), []).append(ln)
        for g, members in groups.items():
            if a.only and a.only != g:
                continue
            whole = vo / ("_chunk-" + g + ".wav")
            if not (a.resplit and whole.exists()):
                speak("\n\n".join(m["text"] for m in members), a.voice, a.model, whole)
            for m, dur in zip(members, split(whole, [vo / (m["id"] + ".wav") for m in members], [len(m["text"].split()) for m in members])):
                durs[m["id"]] = round(dur, 3)
                print(m["id"], durs[m["id"]], flush=True)
        dpath.write_text(json.dumps(durs, indent=1) + "\n")
        return
    for ln in lines:
        if a.only and ln["id"] != a.only:
            continue
        durs[ln["id"]] = round(speak(ln["text"], a.voice, a.model, vo / (ln["id"] + ".wav")), 3)
        print(ln["id"], durs[ln["id"]])
    dpath.write_text(json.dumps(durs, indent=1) + "\n")


if __name__ == "__main__":
    main()
