"""VeerIQ showreel: authored score + effects stem, synthesized deterministically.

120 BPM, 2 s bars, 48 bars (96 s). Writes two 48 kHz stereo WAV stems:
  <out>/score.wav  the music bed
  <out>/sfx.wav    hits, whooshes and UI ticks (bundled library + synthesized)

Run from the project root (needs numpy, scipy and ffmpeg on PATH):
  python scripts/score.py assets/audio assets/sfx <scratch-dir>
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
DUR = 96.0
N = int(SR * DUR)
OUT = Path(sys.argv[1])
SFX_DIR = Path(sys.argv[2])
TMP = Path(sys.argv[3])
rng = np.random.default_rng(4471)  # fixed seed: the render is reproducible


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def sec(t):
    return int(round(t * SR))


def lp(x, fc, order=2):
    return signal.sosfilt(signal.butter(order, min(fc, SR / 2 - 100) / (SR / 2), "low", output="sos"), x)


def hp(x, fc, order=2):
    return signal.sosfilt(signal.butter(order, fc / (SR / 2), "high", output="sos"), x)


def bp(x, lo, hi, order=2):
    return signal.sosfilt(signal.butter(order, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)


def add(buf, start, x, gain=1.0, pan=0.0):
    """Mix mono or stereo x into stereo buf at time start (s) with constant-power pan."""
    i = sec(start)
    if i >= N:
        return
    if x.ndim == 1:
        l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        x = np.stack([x * l * 1.414, x * r * 1.414], axis=1)
    j = min(N, i + len(x))
    if i < 0:
        x = x[-i:]
        i = 0
        j = min(N, len(x))
    buf[i:j] += x[: j - i] * gain


def env(n, a=0.005, d=0.1, s=0.0, r=0.05, hold=None):
    t = np.arange(n) / SR
    e = np.ones(n)
    a_n = max(1, sec(a))
    e[:a_n] = np.linspace(0, 1, a_n)
    after = t[a_n:] - a
    e[a_n:] = s + (1 - s) * np.exp(-after / max(d, 1e-4))
    if r > 0:
        r_n = min(n, sec(r))
        e[-r_n:] *= np.linspace(1, 0, r_n)
    return e


def saw(f, n, phase=0.0):
    t = np.arange(n) / SR
    return 2 * ((t * f + phase) % 1.0) - 1


# ─── instruments ──────────────────────────────────────────────────────────

def kick(gain=1.0):
    n = sec(0.5)
    t = np.arange(n) / SR
    f = 44 + 90 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 6.5)
    click = hp(rng.standard_normal(n), 2500) * np.exp(-t * 400) * 0.35
    return (body + click) * gain


def clap():
    n = sec(0.35)
    t = np.arange(n) / SR
    nz = bp(rng.standard_normal(n), 900, 3800)
    e = np.zeros(n)
    for k, off in enumerate([0.0, 0.011, 0.022]):
        e += (t >= off) * np.exp(-np.maximum(t - off, 0) * (90 if k < 2 else 16))
    return nz * e * 0.5


def hat(open_=False):
    n = sec(0.25 if open_ else 0.06)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7500) * np.exp(-t * (14 if open_ else 70)) * 0.35


def tick(freq=2300, dur=0.03):
    n = sec(dur)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * freq * t) * np.exp(-t * 160)


def pluck(m, dur=0.22, bright=2600):
    n = sec(dur)
    f = mtof(m)
    x = saw(f, n) + 0.6 * saw(f * 1.004, n, 0.3)
    return lp(x, bright) * env(n, 0.002, 0.09, 0.0, 0.02)


def bell(m, dur=1.2):
    n = sec(dur)
    t = np.arange(n) / SR
    f = mtof(m)
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 6)) * np.exp(-t * 3.2)


def boom(dur=2.2, f0=72, f1=38):
    n = sec(dur)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 5)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 2.0)
    nz = lp(rng.standard_normal(n), 900) * np.exp(-t * 9) * 0.6
    crack = hp(rng.standard_normal(n), 3000) * np.exp(-t * 60) * 0.5
    return (body + nz + crack) * 0.9


def thunk(m=40):
    n = sec(0.28)
    t = np.arange(n) / SR
    f = mtof(m) * (1 + 1.2 * np.exp(-t * 40))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 18)
    nz = bp(rng.standard_normal(n), 400, 4000) * np.exp(-t * 55) * 0.7
    return body + nz


def downsweep(dur=0.42):
    n = sec(dur)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t * 7.5) + 40
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.linspace(1, 0.2, n) * 0.6


def riser(dur, lo=250, hi=7000):
    n = sec(dur)
    t = np.arange(n) / SR
    p = t / dur
    nz = rng.standard_normal(n)
    out = np.zeros(n)
    fc = lo * (hi / lo) ** p
    fco = 2 * np.sin(np.pi * fc / SR)
    low = band = 0.0
    q = 0.5
    for i in range(n):  # time-varying state-variable bandpass sweep
        high = nz[i] - low - q * band
        band += fco[i] * high
        low += fco[i] * band
        out[i] = band
    out *= 0.5
    tone = np.sin(2 * np.pi * np.cumsum(180 + 900 * p ** 2) / SR) * 0.25
    return (out * 0.7 + tone) * p ** 2.2


def pad_note(m, n, cutoff, detune=0.006):
    f = mtof(m)
    x = saw(f, n) + saw(f * (1 + detune), n, 0.31) + saw(f * (1 - detune), n, 0.67)
    return lp(x / 3, cutoff, 2)


# ─── score ────────────────────────────────────────────────────────────────

CH = {
    "Dm": ([50, 53, 57, 62], 38), "Bb": ([50, 53, 58, 62], 34), "F": ([53, 57, 60, 65], 41),
    "C": ([52, 55, 60, 64], 36), "Gm": ([50, 55, 58, 62], 43), "A": ([49, 52, 57, 61], 45),
    "D": ([50, 54, 57, 62], 38), "Dsus": ([50, 55, 57, 62], 38),
}
# One chord per 2 s bar (48 bars).
BARS = (
    ["Dm", "Dm", "Dm"]                                   # 0–6   hook
    + ["Dm", "Bb", "F", "C", "Dm"]                       # 6–16  rewind
    + ["F", "C", "Dm", "Bb", "F", "C"]                   # 16–28 idea
    + ["Dm", "Bb", "F", "C", "Dm", "Bb", "C"]            # 28–42 architecture
    + ["Dm", "Dm", "Bb", "Bb", "Gm", "A", "Dm"]          # 42–56 boundary test
    + ["Dm", "Bb", "F", "A"]                             # 56–64 flurry
    + ["Bb", "F", "C", "Dm", "Bb"]                       # 64–74 results
    + ["F", "C", "Dm", "Bb"]                             # 74–82 workspace
    + ["Dm", "Bb", "C"]                                  # 82–88 verify
    + ["Bb", "C", "D", "D"]                              # 88–96 lockup (resolves to D major)
)
assert len(BARS) == 48

# Per-bar intensity: (pad_cutoff, kick, clap, hats, bass, arp, ticks)
def section(b):
    t = b * 2
    if t < 6:   return (700, 0, 0, 0, 0, 0, 1)
    if t < 16:  return (1100, 1, 0, 1, 1, 0, 1)
    if t < 18:  return (1600, 0, 0, 0, 0, 0, 0)
    if t < 28:  return (1900, 1, 0, 1, 1, 0, 0)
    if t < 42:  return (2600, 1, 1, 2, 1, 1, 0)
    if t < 52:  return (900, 0, 0, 0, 2, 0, 1)
    if t < 56:  return (800, 0, 0, 0, 0, 0, 0)
    if t < 64:  return (2400, 1, 1, 2, 1, 1, 0)
    if t < 74:  return (2800, 1, 1, 2, 1, 1, 0)
    if t < 82:  return (2200, 1, 0, 1, 1, 1, 0)
    if t < 88:  return (1200, 0, 0, 1, 1, 0, 1)
    if t < 90:  return (1500, 0, 0, 0, 0, 0, 0)
    return (2600, 0, 0, 0, 1, 0, 0)


music = np.zeros((N, 2))

# Pad: overlapping chord blocks with slow attack/release.
for b, name in enumerate(BARS):
    notes, root = CH[name]
    cut = section(b)[0]
    t0 = b * 2.0
    n = sec(2.0 + 1.2)
    e = env(n, a=0.35, d=4.0, s=0.75, r=1.0)
    blk = np.zeros(n)
    for m in notes:
        blk += pad_note(m, n, cut)
    blk = blk * e * 0.16
    add(music, t0, blk * 0.9, pan=-0.25)
    add(music, t0 + 0.012, blk * 0.9, pan=0.25)
    # Sub drone on the root through the darker sections.
    if section(b)[0] < 1300 or 42 <= t0 < 56:
        tt = np.arange(n) / SR
        drone = np.sin(2 * np.pi * mtof(root) * tt) * e * 0.22
        add(music, t0, drone)

kick_times = []
for b in range(48):
    _, k, c, h, bs, arp, tk = section(b)
    t0 = b * 2.0
    notes, root = CH[BARS[b]]
    for beat in range(4):
        tb = t0 + beat * 0.5
        if k:
            add(music, tb, kick(0.85))
            kick_times.append(tb)
        if c and beat in (1, 3):
            add(music, tb, clap(), 0.55, pan=0.05)
    if h:
        for s16 in range(16 if h == 2 else 8):
            ts = t0 + s16 * (0.125 if h == 2 else 0.25) + (0.125 if h == 1 else 0)
            accent = 1.0 if s16 % 2 == 0 else 0.6
            add(music, ts, hat(open_=(h == 2 and s16 % 8 == 6)), 0.5 * accent, pan=0.35 if s16 % 2 else -0.2)
    if tk:
        for s8 in range(8):
            add(music, t0 + s8 * 0.25, tick(2400 if s8 % 4 == 0 else 1900), 0.09 if s8 % 4 else 0.14, pan=0.5)
    if bs:
        steps = 8 if bs == 1 else 4
        for s in range(steps):
            ts = t0 + s * (2.0 / steps)
            nn = sec(2.0 / steps)
            tt = np.arange(nn) / SR
            f = mtof(root)
            x = np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(2 * np.pi * 2 * f * tt) + 0.12 * saw(f, nn)
            add(music, ts, lp(x, 420) * env(nn, 0.004, 0.16, 0.45, 0.03), 0.42)
    if arp:
        seq = [notes[0] + 12, notes[1] + 12, notes[2] + 12, notes[3] + 12, notes[2] + 12, notes[1] + 12]
        for s16 in range(16):
            add(music, t0 + s16 * 0.125, pluck(seq[s16 % len(seq)], bright=2200 + 800 * (s16 % 4 == 0)), 0.11,
                pan=(-0.45 if s16 % 2 else 0.45))

# Sidechain: duck the pad/bass bed under each kick for pump.
duck = np.ones(N)
tt = np.arange(sec(0.3)) / SR
shape = 1 - 0.45 * np.exp(-tt / 0.09)
for tk in kick_times:
    i = sec(tk)
    j = min(N, i + len(shape))
    duck[i:j] = np.minimum(duck[i:j], shape[: j - i])
music *= duck[:, None]

# Air: silence beats around the big hits so they land.
def carve(t0, t1, depth=0.15):
    i, j = sec(t0), sec(t1)
    ramp = sec(0.06)
    g = np.ones(N)
    g[i:j] = depth
    g[max(0, i - ramp):i] = np.linspace(1, depth, i - max(0, i - ramp))
    g[j:j + ramp] = np.linspace(depth, 1, min(ramp, N - j))
    return g

for a_, b_, d_ in [(15.85, 16.35, 0.05), (51.7, 52.0, 0.25), (89.75, 90.0, 0.3)]:
    music *= carve(a_, b_, d_)[:, None]

# Final fade.
fade = np.ones(N)
fade[sec(94.4):] = np.linspace(1, 0, N - sec(94.4)) ** 1.6
music *= fade[:, None]

# ─── effects stem ─────────────────────────────────────────────────────────

def load(name):
    wav = TMP / (name + ".wav")
    if not wav.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SFX_DIR / (name + ".mp3")), "-ar", str(SR), "-ac", "2", str(wav)], check=True)
    sr, x = wavfile.read(wav)
    x = x.astype(np.float64)
    return x / (32768.0 if np.abs(x).max() > 2 else 1.0)

fx = np.zeros((N, 2))
CUES = [
    # hook
    ("typing", 0.3, 0.18), ("whoosh-short", 0.42, 0.5), ("glitch-1", 4.0, 0.55), ("typing", 4.55, 0.16),
    # rewind
    ("whoosh-short", 6.0, 0.35), ("click", 7.85, 0.5), ("glitch-3", 9.12, 0.4), ("glitch-3", 9.62, 0.4),
    ("glitch-3", 10.12, 0.45), ("whoosh", 11.6, 0.3), ("typing", 13.6, 0.16),
    # idea
    ("sparkle", 16.34, 0.45), ("whoosh-short", 17.45, 0.4), ("ping", 18.47, 0.22), ("whoosh-short", 22.0, 0.3),
    ("click", 22.95, 0.45), ("click", 23.57, 0.45), ("pop", 24.28, 0.35), ("pop", 24.40, 0.35), ("pop", 24.52, 0.35),
    ("whoosh", 27.7, 0.45),
    # architecture
    ("whoosh-short", 29.6, 0.3), ("whoosh-short", 31.6, 0.3), ("key-press", 32.45, 0.3), ("key-press", 32.65, 0.3),
    ("key-press", 32.85, 0.3), ("key-press", 33.05, 0.3), ("pop", 33.3, 0.35), ("whoosh-short", 33.6, 0.3),
    ("whoosh-short", 37.0, 0.3), ("chime", 38.45, 0.4), ("whoosh-short", 39.0, 0.3),
    ("click-soft", 39.55, 0.3), ("click-soft", 39.69, 0.3), ("click-soft", 39.83, 0.3), ("click-soft", 39.97, 0.3),
    ("click-soft", 40.11, 0.3), ("sparkle", 40.45, 0.3), ("whoosh-cinematic", 41.55, 0.45),
    # boundary test
    ("riser", 41.97, 0.5), ("typing", 44.85, 0.2), ("typing", 46.0, 0.2), ("notification", 47.35, 0.22),
    ("whoosh-short", 48.3, 0.3), ("pop", 50.42, 0.35), ("whoosh-cinematic", 50.95, 0.4),
    ("impact-bass-1", 52.0, 0.95), ("glitch-1", 52.0, 0.6), ("glitch-3", 52.5, 0.35), ("typing", 52.45, 0.14),
    ("click-soft", 53.5, 0.3), ("click-soft", 53.64, 0.3), ("click-soft", 53.78, 0.3), ("ping", 54.3, 0.2),
    # results
    ("impact-bass-1", 64.12, 0.55), ("click-soft", 65.05, 0.28), ("click-soft", 65.17, 0.28), ("click-soft", 65.29, 0.28),
    ("whoosh-short", 66.2, 0.28), ("ping", 67.82, 0.28), ("whoosh-short", 68.4, 0.28), ("glitch-3", 69.65, 0.32),
    ("whoosh-short", 70.6, 0.28), ("pop", 71.6, 0.22), ("pop", 71.67, 0.22), ("pop", 71.74, 0.22), ("pop", 71.81, 0.22),
    ("whoosh-cinematic", 72.35, 0.38), ("whoosh-short", 73.72, 0.35),
    # workspace
    ("whoosh-short", 74.0, 0.28), ("whoosh", 75.45, 0.3), ("whoosh", 77.35, 0.3), ("whoosh", 79.25, 0.3),
    # verify
    ("whoosh-short", 82.0, 0.28), ("typing", 82.5, 0.22), ("chime", 83.6, 0.35), ("typing", 84.55, 0.22),
    ("error", 85.55, 0.3), ("glitch-3", 85.55, 0.3), ("whoosh", 87.55, 0.25),
    # lockup
    ("impact-bass-1", 90.0, 0.9), ("glitch-1", 90.0, 0.4), ("whoosh-short", 91.85, 0.32), ("sparkle", 92.35, 0.38),
    ("whoosh-short", 92.55, 0.22),
]
for name, t, g in CUES:
    add(fx, t, load(name), g)

# Synthesized hits.
add(fx, 4.0, boom(2.0), 0.55)
for t, m in [(8.12, 81), (8.62, 84)]:
    add(fx, t, bell(m), 0.16, pan=0.2)
for t in (9.12, 9.62, 10.12):
    add(fx, t, thunk(38), 0.35)
add(fx, 15.6, downsweep(), 0.5)
for j, m in enumerate([62, 65, 69, 72, 74, 77]):           # gate passes climb a D-minor line
    add(fx, 34.62 + j * 0.3, pluck(m + 12, 0.35, 4000), 0.22, pan=-0.3 + j * 0.12)
    add(fx, 34.62 + j * 0.3, tick(3200), 0.08)
add(fx, 37.62, thunk(36), 0.3)
add(fx, 48.55, riser(3.4, 120, 2400), 0.25)
add(fx, 52.0, boom(3.0, 80, 34), 0.8)
add(fx, 52.0, hp(rng.standard_normal(sec(1.2)), 1500) * np.exp(-np.arange(sec(1.2)) / SR * 5), 0.22)
# Flurry: 22 more hits, accelerating — same schedule as the picture.
t, gap = 0.45, 0.42
for k in range(22):
    pan = float(np.sin(k * 2.3)) * 0.6
    add(fx, 56 + t, thunk(36 + (k % 3)), 0.42, pan=pan)
    add(fx, 56 + t, tick(2600 + 40 * k, 0.02), 0.1, pan=pan)
    t += gap
    gap *= 0.93
last = 56 + t - gap / 0.93
add(fx, last + 0.18, boom(2.4, 76, 36), 0.6)
add(fx, last + 0.18, bell(74, 2.0), 0.12)
# Count ticks for 18 of 24 and the test chord.
for k in range(1, 19):
    p = 1 - (1 - (k - 0.5) / 18) ** (1 / 3)
    add(fx, 66.62 + 1.2 * p, tick(2800 + 30 * k, 0.018), 0.12)
for k in range(1, 14):
    p = 1 - (1 - (k - 0.5) / 13) ** (1 / 3)
    add(fx, 71.0 + 1.2 * p, tick(3000, 0.018), 0.1)
add(fx, 90.0, boom(3.2, 70, 32), 0.7)
add(fx, 88.0, riser(2.0, 200, 5000), 0.18)
for t, m in [(92.4, 74), (92.6, 78), (92.8, 81)]:            # D-major arpeggio under the wordmark
    add(fx, t, bell(m, 2.4), 0.12, pan=(m - 78) / 10)

fx *= fade[:, None]

# ─── master each stem ─────────────────────────────────────────────────────
OUT.mkdir(parents=True, exist_ok=True)

def write(name, x, peak_db):
    x = np.tanh(x * 1.1) / np.tanh(1.1)   # gentle soft clip
    pk = np.abs(x).max()
    x = x / pk * 10 ** (peak_db / 20)
    wavfile.write(OUT / name, SR, (x * 32767).astype(np.int16))
    print(name, "peak", round(20 * np.log10(np.abs(x).max()), 2), "dB")

write("score.wav", music, -3.0)
write("sfx.wav", fx, -2.0)
