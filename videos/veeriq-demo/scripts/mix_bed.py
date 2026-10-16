"""Music bed and effects for the VeerIQ submission video (deterministic, synthesized locally).

The bed is an original ambient pad in D minor with a soft arpeggio (no third-party music, nothing to
license), ducked under the narration with an envelope computed from the placed narration clips. Effects
use the bundled HyperFrames sound library in assets/sfx (see assets/sfx/CREDITS.md).
Reads assets/audio/timeline.json (scripts/build.py); writes assets/audio/music.wav and assets/audio/sfx.wav.

  python scripts/mix_bed.py      # needs numpy, scipy and ffmpeg
"""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
TL = json.loads((ROOT / "assets/audio/timeline.json").read_text())
SR = 48000
N = int(TL["total"] * SR)
S = TL["starts"]


def sec(t):
    return int(round(t * SR))


def lp(x, fc):
    return signal.sosfilt(signal.butter(2, fc / (SR / 2), "low", output="sos"), x)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# ── bed: one chord per 4 s, overlapping blocks with slow attack and release ──
CHORDS = [[50, 57, 62, 65], [46, 53, 58, 62], [41, 48, 53, 57], [48, 55, 60, 64]]  # Dm Bb F C
bed = np.zeros((N, 2))
t = np.arange(sec(6.0)) / SR
for i in range(int(TL["total"] // 4) + 2):
    t0, ch = i * 4.0, CHORDS[i % 4]
    env = np.clip(t / 1.5, 0, 1) * np.clip((6.0 - t) / 2.0, 0, 1)
    blk = np.zeros(len(t))
    for m in ch:
        f = mtof(m + 12)
        blk += (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2.003 * f * t)) * 0.05
    blk = lp(blk * env, 1400)
    a, b = sec(t0), min(N, sec(t0) + len(t))
    if a < N:
        bed[a:b, 0] += blk[: b - a] * 0.9
        bed[a:b, 1] += np.roll(blk, 300)[: b - a] * 0.9
# soft plucked arpeggio, 8ths at 96 bpm, through the middle acts only
step = 60 / 96 / 2
for k in range(int(TL["total"] / step)):
    st = k * step
    if not (S["promise"] <= st < S["outro"]):
        continue
    ch = CHORDS[int(st // 4) % 4]
    m = ch[[0, 2, 3, 1, 2, 3, 1, 2][k % 8]] + 24
    n = sec(1.2)
    tt = np.arange(n) / SR
    w = np.sin(2 * np.pi * mtof(m) * tt) * np.exp(-tt * 4.0) * np.clip(tt / 0.006, 0, 1) * 0.03
    a = sec(st)
    b = min(N, a + n)
    pan = 0.35 if k % 2 else 0.65
    bed[a:b, 0] += w[: b - a] * (1 - pan)
    bed[a:b, 1] += w[: b - a] * pan
# stereo echo, fades
d = sec(0.37)
bed[d:] += 0.25 * bed[:-d][:, ::-1]
fade = np.clip(np.arange(N) / SR / 2.5, 0, 1) * np.clip((TL["total"] - np.arange(N) / SR) / 3.0, 0, 1)
bed *= fade[:, None]

# ── duck the bed under the narration ──
# One smooth dip per narration line (not per syllable, which made the bed pump in every gap between words).
active = np.zeros(N)
for lid, a in TL["vo"]:
    i, j = sec(a - 0.25), min(N, sec(a + TL["durations"][lid] + 0.35))
    active[max(0, i):j] = 1.0
att = signal.sosfiltfilt(signal.butter(2, 1.2 / (SR / 2), "low", output="sos"), active)  # ~0.4 s glide, zero-phase
gain = 1.0 - 0.6 * np.clip(att, 0, 1)                  # about -8 dB under speech, swells back between lines
bed *= gain[:, None]

# ── effects on the key moments ──
fx = np.zeros((N, 2))
tmp = Path(tempfile.mkdtemp())


def load(name):
    wav = tmp / (name + ".wav")
    if not wav.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "assets/sfx" / (name + ".mp3")), "-ar", str(SR), "-ac", "2", str(wav)], check=True)
    sr, x = wavfile.read(wav)
    return x.astype(np.float64) / 32768.0


def add(name, t, g):
    x = load(name) * g
    i = sec(t)
    j = min(N, i + len(x))
    fx[i:j] += x[: j - i]


for name in ("story", "brand", "promise", "system", "judges", "flurry", "console", "mcp", "integrate", "import", "expect", "learned", "outro"):
    add("whoosh-short", max(0, S[name] - 0.05), 0.22)
add("impact-bass-2", S["hook"] + 4.1, 0.4)       # the database is wiped
add("sparkle", S["brand"] + 1.4, 0.3)
add("impact-bass-1", S["judges"] + 31.6, 0.55)   # "ArmorIQ stopped it" on screen
add("chime", S["judges"] + 54.0, 0.22)            # the judge's approval commits
add("impact-bass-2", S["mcp"] + 8.9, 0.45)        # MCP refusal
add("chime", S["import"] + 16.4, 0.25)            # import result
add("ping", S["expect"] + 19.85, 0.25)            # zero forbidden effects
add("error", S["judges"] + 62.9, 0.22)            # one changed cent fails verification
add("impact-bass-1", S["outro"] + 2.0, 0.45)      # the boundary held
rng = np.random.default_rng(4471)


def bp(x, lo, hi):
    return signal.sosfilt(signal.butter(2, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)


def hpf(x, fc):
    return signal.sosfilt(signal.butter(2, fc / (SR / 2), "high", output="sos"), x)


def thunk(m=40):
    n = sec(0.28)
    tt = np.arange(n) / SR
    f = mtof(m) * (1 + 1.2 * np.exp(-tt * 40))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 18)
    return body + bp(rng.standard_normal(n), 400, 4000) * np.exp(-tt * 55) * 0.7


def tick(freq=2300, dur=0.03):
    tt = np.arange(sec(dur)) / SR
    return np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 160)


def boom(dur=2.2, f0=72, f1=38):
    n = sec(dur)
    tt = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-tt * 5)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 2.0)
    return (body + lp(rng.standard_normal(n), 900) * np.exp(-tt * 9) * 0.6 + hpf(rng.standard_normal(n), 3000) * np.exp(-tt * 60) * 0.5) * 0.9


def bell(m, dur=1.2):
    tt = np.arange(sec(dur)) / SR
    f = mtof(m)
    return (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 6)) * np.exp(-tt * 3.2)


def addsig(t0, x, g, pan=0.0):
    i = sec(t0)
    j = min(N, i + len(x))
    if i >= N or j <= i:
        return
    fx[i:j, 0] += x[: j - i] * g * (1 - pan) / 2 ** 0.5 * 1.4
    fx[i:j, 1] += x[: j - i] * g * (1 + pan) / 2 ** 0.5 * 1.4


# The boundary flurry: each request that hits the wall is destroyed with a hit; 23/23 lands on a boom.
F0 = S["flurry"]
addsig(F0 + 0.02, thunk(36), 0.45)          # attempt 01, already on the wall as the scene opens
tq, gap = 0.45, 0.42
for k in range(22):
    pan = float(np.sin(k * 2.3)) * 0.6
    addsig(F0 + tq, thunk(36 + (k % 3)), 0.42, pan)
    addsig(F0 + tq, tick(2600 + 40 * k, 0.02), 0.1, pan)
    tq += gap
    gap *= 0.93
last = F0 + tq - gap / 0.93
addsig(last + 0.18, boom(2.4, 76, 36), 0.6)
addsig(last + 0.18, bell(74, 2.0), 0.12)
# Softer replacements for the old glitch effects: the three things a backup brings back land as thunks.
for tb in (11.0, 12.95, 15.1):
    addsig(S["story"] + tb, thunk(38), 0.3)
fx *= fade[:, None]


def write(path, x, peak_db):
    x = np.tanh(x * 1.1) / np.tanh(1.1)
    x = x / (np.abs(x).max() or 1) * 10 ** (peak_db / 20)
    wavfile.write(path, SR, (x * 32767).astype(np.int16))


write(ROOT / "assets/audio/music.wav", bed, -14.0)
write(ROOT / "assets/audio/sfx.wav", fx, -8.0)
print("music.wav and sfx.wav: %.2f s" % TL["total"])
