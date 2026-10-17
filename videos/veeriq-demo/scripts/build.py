"""Assemble the VeerIQ submission video timeline from the narration.

Writes index.html (scenes, recorded footage, overlays, HUD, captions, audio), compositions/captions.html,
the HUD section list in compositions/hud.html, and assets/audio/timeline.json (for scripts/mix_bed.py).
Scene lengths and narration placements live in SCENES below; narration durations and word times come from
assets/vo/durations.json and assets/vo/words.json (scripts/align_vo.py).

  python scripts/build.py
"""
import difflib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VO = json.loads((ROOT / "assets/vo/durations.json").read_text())
WORDS = json.loads((ROOT / "assets/vo/words.json").read_text())
TEXT = {x["id"]: x["text"] for x in json.loads((ROOT / "scripts/narration.json").read_text())}

# (name, composition id or None, file, length s, [(narration id, offset s)], hud section label or None)
SCENES = [
    ("hook", "hook", "00-hook.html", 15.6, [("h01", 0.4)], "The problem"),
    ("story", "story", "01-story.html", 20.4, [("l01", 0.5)], None),
    ("brand", "brand", "03-brand.html", 7.0, [("l02", 1.25)], "Meet VeerIQ"),
    ("promise", "promise", "02-promise.html", 12.6, [("l03", 0.4)], "How it works"),
    ("system", "system", "04b-system.html", 18.6, [("l04", 0.4)], None),
    ("judges", None, None, 64.5, [("j1", 0.3), ("j2", 14.0), ("j3", 31.0), ("j4", 42.6), ("j5", 56.6)], "Try it live"),
    ("flurry", "flurry", "07-flurry.html", 8.4, [], None),  # 23 attempts hit the boundary, 23 destroyed (no voice; the hits carry it)
    ("console", "console", "05d-console.html", 18.6, [("l05f", 1.0), ("l05e", 9.9)], None),
    ("mcp", "mcplive", "08b-mcp-live.html", 12.6, [("l06", 0.3)], "Bring your agent"),
    ("integrate", "integrate", "07-integrate.html", 13.6, [("l07a", 0.4), ("l07b", 6.4)], "Plug it in"),
    ("import", None, None, 23.74, [("l07c", 0.3), ("l07d", 11.4)], None),
    ("expect", "expect", "08-expect.html", 22.8, [("l08", 0.4)], "What to expect"),
    ("learned", "learned", "12-learned.html", 19.0, [("l10", 0.4)], "What's next"),
    ("outro", "outro", "11-outro.html", 12.0, [("l11", 3.7)], "VeerIQ"),
]
# Recorded footage inside a scene: (scene, clip id, file, start in scene, length, source start, rate)
IM = json.loads((ROOT / "assets/footage/import.marks.json").read_text())
# The judges take (scripts/capture.mjs judges): the four-step start page, cut on its marks so a re-recorded take
# drops in. Each segment: (scene start, length, source start, source end) -> playback rate = source span / length.
JM = json.loads((ROOT / "assets/footage/judges.marks.json").read_text())
CUT_AT, CUT_LEN = 35.6, 0.8
_B = round(JM["runStart"] + 0.2 - (JM["s2"] - 0.2), 2)  # step 2 intro plays at 1x
JSEG = [
    # scene start, length, source from, source to, step, label
    (0.0, 13.8, JM["home"] + 0.8, JM["s2"] - 0.2, "1", "The damage"),
    (13.8, _B, JM["s2"] - 0.2, JM["runStart"] + 0.2, "2", "Undo it two ways"),          # at 1x
    (13.8 + _B, 31.6 - 13.8 - _B, JM["runStart"] + 0.2, JM["blockSeen"] + 0.4, "2", "A live model works"),
    (31.6, 4.0, JM["blockSeen"] + 0.4, JM["blockSeen"] + 4.4, "2", "ArmorIQ blocks the trap"),
    (CUT_AT + CUT_LEN, 42.6 - CUT_AT - CUT_LEN, JM["runEnd"] + 1.0, JM["s3"] - 0.4, "2", "Only the damage repaired"),
    (42.6, 4.1, JM["s3"] - 0.4, JM["awaiting"], "3", "The agent prepares the change"),
    (46.7, 6.5, JM["awaiting"], JM["approve"] + 0.1, "3", "You are the second key"),
    (53.2, 3.2, JM["committed"] - 0.4, JM["committed"] + 2.8, "3", "Committed in one transaction", "1× · cut 5 s"),
    (56.4, 8.1, JM["s4"] - 0.3, JM["tampered"] + 2.4, "4", "Check our work"),
]
SKIPPED = round(JM["runEnd"] + 1.0 - (JM["blockSeen"] + 4.4))  # model time the cut card stands in for


def _rate(seg):
    st, ln, a, b = seg[:4]
    return round(max(0.25, (b - a) / ln), 3)


FOOTAGE = [("judges", "jv-%d" % i, "judges.mp4", seg[0], round(seg[1], 3), round(seg[2], 2), _rate(seg)) for i, seg in enumerate(JSEG)]
FOOTAGE += [
    ("import", "im-1", "import.mp4", 0.0, 11.09, 0.3, 1.75),  # load sample, map columns, validate
    ("import", "im-2", "import.mp4", 11.09, 5.25, 24.5, 2.0), # review the permission, authorize
    ("import", "im-3", "import.mp4", 16.34, 7.4, round(IM["result"] - 0.6, 2), 1.0),  # result, signed evidence
]
OVERLAYS = {"judges": ("judgesov", "05j-judges-ov.html"), "import": ("importov", "07b-import-ov.html")}
FRAME = "left:209px; top:98px; width:1502px; height:846px; right:auto; bottom:auto; object-fit:cover;"

starts, t = {}, 0.0
for name, *_rest in SCENES:
    starts[name] = round(t, 3)
    t += [s for s in SCENES if s[0] == name][0][3]
TOTAL = round(t, 3)


def norm(w):
    w = re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))
    return {"veeriq": "vriq", "veeriqs": "vriqs", "eightyfour": "84", "twentythree": "23", "armoriq": "armor"}.get(w, w)


def timed_words(lid):
    """Script words with times: matched to the transcript where possible, interpolated otherwise."""
    script = TEXT[lid].split()
    heard = WORDS[lid]
    hn = []
    for w, s, e in heard:   # whisper splits "ArmorIQ" into "Armor" + "IQ"; keep the first part's time
        hn.append((norm(w), s, e))
    sm = difflib.SequenceMatcher(a=[norm(w) for w in script], b=[h[0] for h in hn], autojunk=False)
    times = [None] * len(script)
    for b in sm.get_matching_blocks():
        for k in range(b.size):
            times[b.a + k] = (hn[b.b + k][1], hn[b.b + k][2])
    dur = VO[lid]
    known = [i for i, x in enumerate(times) if x]
    for i in range(len(script)):
        if times[i]:
            continue
        prev = max([k for k in known if k < i], default=None)
        nxt = min([k for k in known if k > i], default=None)
        a = times[prev][1] if prev is not None else 0.0
        b = times[nxt][0] if nxt is not None else dur
        lo = prev if prev is not None else -1
        hi = nxt if nxt is not None else len(script)
        f = (i - lo) / (hi - lo)
        st = a + (b - a) * f
        times[i] = (st, min(b, st + 0.35))
    return list(zip(script, times))


def cues():
    out = []
    for name, cid, f, length, vo, sec in SCENES:
        for lid, off in vo:
            t0 = starts[name] + off
            words = timed_words(lid)
            cur = []
            for i, (w, (s, e)) in enumerate(words):
                cur.append((w, s, e))
                text = " ".join(x[0] for x in cur)
                end_sentence = re.search(r"[.?!:;]$", w) and len(cur) >= 2
                comma = w.endswith(",") and len(cur) >= 5
                if end_sentence or comma or len(cur) >= 7 or len(text) > 44 or i == len(words) - 1:
                    out.append([round(t0 + cur[0][1], 3), round(t0 + cur[-1][2], 3), text])
                    cur = []
    for i in range(len(out) - 1):           # hold each cue until the next one (when the gap is small)
        if out[i + 1][0] - out[i][1] < 0.8:
            out[i][1] = out[i + 1][0] - 0.02
        else:
            out[i][1] += 0.35
    out[-1][1] += 0.6
    return out


def write_captions(cs):
    divs, sets = [], []
    for i, (a, b, text) in enumerate(cs):
        divs.append('          <div class="cap" id="cap-%d"><span>%s</span></div>' % (i, html.escape(text)))
        sets.append("[%.3f, %.3f]" % (a, b))
    (ROOT / "compositions/captions.html").write_text("""<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template id="captions-template">
      <style>
        @font-face { font-family: "Instrument Serif"; font-style: normal; font-weight: 400; src: url("../assets/fonts/InstrumentSerif-normal-400.woff2") format("woff2"); }
        #root { position: absolute; inset: 0; pointer-events: none; }
        .cap { position: absolute; left: 0; right: 0; top: 954px; display: flex; justify-content: center; visibility: hidden; }
        .cap span { padding: 4px 22px 7px; background: rgba(14,14,16,0.86); border-radius: 6px; font-family: "Instrument Serif", serif; font-size: 40px; line-height: 46px; letter-spacing: -0.005em; color: #f2f1ed; white-space: nowrap; }
      </style>
      <div id="root" data-composition-id="captions" data-width="1920" data-height="1080">
%s
      </div>
      <script>
        (function () {
          var tl = gsap.timeline({ paused: true });
          // One caption track, generated by scripts/build.py from the narration's word timings.
          var CUES = [%s];
          CUES.forEach(function (c, i) {
            tl.set("#cap-" + i, { visibility: "visible" }, c[0]);
            tl.fromTo("#cap-" + i + " span", { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.12, ease: "power2.out", immediateRender: false }, c[0]);
            tl.set("#cap-" + i, { visibility: "hidden" }, c[1]);
          });
          window.__timelines["captions"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
""" % ("\n".join(divs), ", ".join(sets)))


def write_hud():
    p = ROOT / "compositions/hud.html"
    s = p.read_text()
    secs = [(starts[name], label) for name, cid, f, l, vo, label in SCENES if label]
    s = re.sub(r"var DUR = [0-9.]+;", "var DUR = %s;" % TOTAL, s)
    s = re.sub(r"var SECTIONS = \[[^\]]*\];", "var SECTIONS = [%s];" % ", ".join("%g" % a for a, _ in secs), s)
    block = "\n".join('          <div class="hud-sec" id="hud-sec-%d"><b>%02d</b>&nbsp;&nbsp;%s</div>' % (i, i + 1, html.escape(lbl)) for i, (_, lbl) in enumerate(secs))
    s = re.sub(r'(<div[^>]*id="hud-section">\n)(?:\s*<div[^>]*class="hud-sec".*?</div>\n)+', lambda m: m.group(1) + block + "\n", s, flags=re.S)
    s = re.sub(r"&nbsp;&nbsp;/&nbsp;&nbsp;Showreel 2026", "&nbsp;&nbsp;/&nbsp;&nbsp;Flow State submission", s)
    p.write_text(s)


def write_judges_overlay():
    """Step labels, real playback rates and the cut length of the judges take, into its overlay."""
    p = ROOT / "compositions/frames/05j-judges-ov.html"
    s = p.read_text()
    fmt = lambda r: ("%.2f" % r).rstrip("0").rstrip(".") + "×"
    segs = [[round(seg[0], 2), seg[4], seg[5], seg[6] if len(seg) > 6 else fmt(_rate(seg))] for seg in JSEG]
    length = [x for x in SCENES if x[0] == "judges"][0][3]
    s = re.sub(r"/\*SEGMENTS\*/.*?/\*END\*/", lambda m: "/*SEGMENTS*/" + json.dumps(segs, ensure_ascii=False) + "/*END*/", s)
    s = re.sub(r"/\*CUT\*/.*?/\*END\*/", "/*CUT*/[%g, %g]/*END*/" % (CUT_AT, CUT_LEN), s)
    s = re.sub(r"/\*LENGTH\*/.*?/\*END\*/", "/*LENGTH*/%g/*END*/" % length, s)
    s = re.sub(r'(<span id="jo-cut-text">)[^<]*(</span>)', lambda m: m.group(1) + "The run finishes %d seconds later." % SKIPPED + m.group(2), s)
    p.write_text(s)


def write_index():
    rows = ['      <!-- Scenes: one sub-composition each; recorded footage and its overlay in the live and import acts. -->']
    for name, cid, f, length, vo, sec in SCENES:
        if cid:
            rows.append('      <div id="el-%s" data-composition-id="%s" data-composition-src="compositions/frames/%s" data-start="%g" data-duration="%g" data-track-index="1" data-width="1920" data-height="1080"></div>' % (name, cid, f, starts[name], length))
    rows.append('      <!-- Real product recordings (Playwright, 1080p). Rates and cuts are labelled on screen by the overlays. -->')
    for scene, vid, f, st, ln, ms, rate in FOOTAGE:
        rows.append('      <video id="%s" class="clip" src="assets/footage/%s" data-start="%g" data-duration="%g" data-media-start="%g" data-playback-rate="%g" data-track-index="2" muted playsinline style="position:absolute; %s"></video>' % (vid, f, round(starts[scene] + st, 3), ln, ms, rate, FRAME))
    rows.append('      <!-- Persistent chrome, then the footage overlays (their rails sit at the frame edge), then captions. -->')
    rows.append('      <div id="el-hud" data-composition-id="hud" data-composition-src="compositions/hud.html" data-start="0" data-duration="%g" data-track-index="4" data-width="1920" data-height="1080"></div>' % TOTAL)
    for scene, (cid, f) in OVERLAYS.items():
        length = [s for s in SCENES if s[0] == scene][0][3]
        rows.append('      <div id="el-%s" data-composition-id="%s" data-composition-src="compositions/frames/%s" data-start="%g" data-duration="%g" data-track-index="3" data-width="1920" data-height="1080"></div>' % (cid, cid, f, starts[scene], length))
    rows.append('      <div id="el-captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-track-kind="captions" data-start="0" data-duration="%g" data-track-index="5" data-width="1920" data-height="1080"></div>' % TOTAL)
    rows.append('      <!-- Narration (Gemini TTS, one clip per line), music bed and effects (scripts/mix_bed.py). -->')
    placements = []
    for name, cid, f, length, vo, sec in SCENES:
        for lid, off in vo:
            a = round(starts[name] + off, 3)
            placements.append((lid, a))
            rows.append('      <audio id="vo-%s" src="assets/vo/%s.wav" data-start="%g" data-duration="%g" data-track-index="10" data-volume="1"></audio>' % (lid, lid, a, VO[lid]))
    rows.append('      <audio id="el-music" src="assets/audio/music.wav" data-start="0" data-duration="%g" data-track-index="11" data-volume="1"></audio>' % TOTAL)
    rows.append('      <audio id="el-sfx" src="assets/audio/sfx.wav" data-start="0" data-duration="%g" data-track-index="12" data-volume="1"></audio>' % TOTAL)
    head = (ROOT / "index.html").read_text().split("<body>")[0]
    head = re.sub(r"\s*\.clip-frame[^\n]*", "", head)
    (ROOT / "index.html").write_text(head + """<body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="%g" data-width="1920" data-height="1080">
%s
    </div>
    <script>
      window.__timelines["main"] = gsap.timeline({ paused: true });
    </script>
  </body>
</html>
""" % (TOTAL, "\n".join(rows)))
    (ROOT / "assets/audio").mkdir(parents=True, exist_ok=True)
    (ROOT / "assets/audio/timeline.json").write_text(json.dumps({"total": TOTAL, "starts": starts, "vo": placements, "durations": VO}, indent=1) + "\n")


if __name__ == "__main__":
    cs = cues()
    write_captions(cs)
    write_hud()
    write_judges_overlay()
    write_index()
    print("total %.2f s, %d captions, judges rates %s, cut %ds" % (TOTAL, len(cs), [_rate(x) for x in JSEG], SKIPPED))
    for name in starts:
        print("  %-9s %7.2f" % (name, starts[name]))
