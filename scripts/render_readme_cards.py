#!/usr/bin/env python3
"""Render the animated SVG cards for the GitHub profile README.

Reads  profile.json            (text, tiles, featured repos)
       data/contributions.json (daily counts, refreshed by the Action)
       data/repos.json         (featured repo metadata, refreshed by the Action)
Writes cards/*.svg and the card block of README.md.

Look: paper cards, Instrument Serif with italic words, Geist and Geist Mono,
one accent colour, three solid tiles. Page order and timing:

  hero (0s) -> blue graph (0.8s) -> monthly bars (1.9s) -> tiles (3.1s)
  -> "What I'm coding" (4.4s) -> repos (4.6s)

GitHub shows README images through <img>: no scripts, no external requests.
So each card embeds its own subset fonts (base64 WOFF), animates with CSS
keyframes in its own <style> plus SMIL, and rests on its final frame:

  prefers-reduced-motion  -> CSS switches every animation off, SMIL groups hidden
  STATIC=1                -> same final frame baked in, for screenshots

Usage:  python scripts/render_readme_cards.py
        STATIC=1 python scripts/render_readme_cards.py   (also writes preview/index.html)
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cards"
STATIC = os.environ.get("STATIC") == "1"

PAPER, INK, BODY, MUTED, FAINT, RULE = "#f3f3f1", "#111111", "#3a3a3c", "#6e6e73", "#8e8e93", "#dcdcd7"
EMPTY, PENDING = "#e2e2de", "#c8c8c2"
W = 880           # full-width card
GAP = 12          # space under every card, drawn inside the image
TILE_W = W / 3    # three tiles per row at 33.333%

FONTS = {  # (family, style, weight) -> file
    ("serif", "normal", 400): "fonts/instrument-serif-latin-400-normal.woff",
    ("serif", "italic", 400): "fonts/instrument-serif-latin-400-italic.woff",
    ("sans", "normal", 400): "fonts/geist-sans-latin-400-normal.woff",
    ("sans", "normal", 600): "fonts/geist-sans-latin-600-normal.woff",
    ("mono", "normal", 400): "fonts/geist-mono-latin-400-normal.woff",
}
FAMILY = {"serif": "'Instrument Serif', Georgia, serif",
          "sans": "Geist, system-ui, -apple-system, sans-serif",
          "mono": "'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace"}
FACE_NAME = {"serif": "Instrument Serif", "sans": "Geist", "mono": "Geist Mono"}
SERIF, SERIF_I, SANS, SANS_B, MONO = FONTS.keys()

T = dict(hero=0.0, heatmap=0.8, activity=1.9, tiles=3.1, title=4.4, repos=4.6)
EASE = "cubic-bezier(.2,.7,.2,1)"


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
@lru_cache(None)
def _metrics(key):
    f = TTFont(ROOT / FONTS[key])
    return f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm


def tw(s: str, key, size: float) -> float:
    cmap, hmtx, upm = _metrics(key)
    sp = hmtx[cmap[32]][0]
    return sum(hmtx[cmap[ord(c)]][0] if ord(c) in cmap else sp for c in s) * size / upm


def wrap(s: str, key, size: float, maxw: float, max_lines: int = 99) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if tw(trial, key, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while tw(last + "…", key, size) > maxw and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(",.;:-") + "…"
    return lines


@lru_cache(None)
def font_face(key, chars: str) -> str:
    """Subset to `chars` (pyftsubset's job) and embed as a base64 WOFF @font-face."""
    font = TTFont(ROOT / FONTS[key])
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern", "liga", "calt"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.drop_tables += ["FFTM"]
    s = subset.Subsetter(opts)
    s.populate(text=chars)
    s.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    fam, style, weight = key
    return (f"@font-face{{font-family:'{FACE_NAME[fam]}';font-style:{style};font-weight:{weight};"
            f"src:url(data:font/woff;base64,{base64.b64encode(buf.getvalue()).decode()}) format('woff')}}")


# --------------------------------------------------------------------------
# Motion. Resting style = final frame; keyframes run from hidden to rest
# with fill-mode both, so "animation:none" anywhere shows the end state.
# --------------------------------------------------------------------------
KEYFRAMES = """
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes show{from{opacity:0}to{opacity:1}}
@keyframes grow{from{transform:scaleY(0)}to{transform:none}}
@keyframes pop{0%{opacity:0;transform:scale(.3)}70%{opacity:1;transform:scale(1.15)}100%{opacity:1;transform:none}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
@keyframes nudge{0%,100%{transform:none}50%{transform:translateX(4px)}}
@keyframes nudgeup{0%,100%{transform:none}50%{transform:translate(3px,-3px)}}
@keyframes tilein{0%{opacity:0;transform:translateY(90px) scale(.6) rotate(-9deg)}55%{opacity:1;transform:translateY(-10px) scale(1.05) rotate(2deg)}75%{transform:translateY(3px) scale(.98) rotate(-.8deg)}90%{transform:translateY(-1px) scale(1.01) rotate(.2deg)}100%{opacity:1;transform:none}}
@keyframes slidein{from{opacity:0;transform:translateX(-26px)}to{opacity:1;transform:none}}
@keyframes arrowin{0%{opacity:0;transform:translateX(-30px)}60%{opacity:1;transform:translateX(6px)}100%{opacity:1;transform:none}}
@keyframes roll{from{transform:translateY(60px)}to{transform:none}}
@keyframes sheen{0%{transform:translateX(-260px) skewX(-20deg)}22%,100%{transform:translateX(420px) skewX(-20deg)}}
@keyframes ring{0%{opacity:.7;transform:scale(.2)}100%{opacity:0;transform:scale(2.4)}}
.b{transform-box:fill-box}
.c{transform-box:fill-box;transform-origin:center}
.bot{transform-box:fill-box;transform-origin:50% 100%}
.tile{transform-box:fill-box;transform-origin:50% 60%}
.rg,.sh{opacity:0}
"""
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}.smil,.sh,.rg{display:none}}"


def anim(name, dur, delay, ease=EASE):
    return f"animation:{name} {dur}s {ease} {delay:.3f}s both"


def loop(name, dur, delay, ease="ease-in-out"):
    return f"animation:{name} {dur}s {ease} {delay:.3f}s infinite"


# --------------------------------------------------------------------------
# Card builder
# --------------------------------------------------------------------------
class Card:
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.parts, self.defs, self.css = [], [], []
        self.chars = defaultdict(set)

    def add(self, *s):
        self.parts.extend(s)

    def text(self, x, y, runs, size, fill=INK, cls="", style="", anchor=None, attrs=""):
        """runs: a string, or a list of (text, font_key[, fill]) for mixed upright/italic."""
        if isinstance(runs, str):
            runs = [(runs, SANS)]
        first = runs[0][1]
        fam, fstyle, wt = first
        inner = ""
        for i, run in enumerate(runs):
            s, key = run[0], run[1]
            self.chars[key].update(s)
            if i == 0:
                inner += escape(s)
            else:
                a = ""
                if key[1] != fstyle:
                    a += f' font-style="{key[1]}"'
                if key[2] != wt:
                    a += f' font-weight="{key[2]}"'
                if key[0] != fam:
                    a += f' font-family="{FAMILY[key[0]]}"'
                if len(run) > 2:
                    a += f' fill="{run[2]}"'
                inner += f"<tspan{a}>{escape(s)}</tspan>"
        a = f' text-anchor="{anchor}"' if anchor else ""
        a += f' class="{cls}"' if cls else ""
        a += f' style="{style}"' if style else ""
        fs = f' font-style="{fstyle}"' if fstyle != "normal" else ""
        fw = f' font-weight="{wt}"' if wt != 400 else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FAMILY[fam]}"{fs}{fw} font-size="{size}" '
                f'fill="{fill}"{a}{attrs}>{inner}</text>')

    def smil(self, s):
        return "" if STATIC else f'<g class="smil">{s}</g>'

    def svg(self) -> str:
        faces = "".join(font_face(k, "".join(sorted(v | {" "}))) for k, v in sorted(self.chars.items()))
        css = faces + KEYFRAMES + "".join(self.css) + REDUCED + ("*{animation:none!important}" if STATIC else "")
        css = re.sub(r"\s*\n\s*", "", css)
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        w = f"{self.w:.3f}".rstrip("0").rstrip(".")
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{self.h}" viewBox="0 0 {w} {self.h}" '
                f'role="img" aria-label="{escape(self.title, {chr(34): "&quot;"})}"><title>{escape(self.title)}</title>'
                f"<style>{css}</style>{defs}" + "".join(self.parts) + "</svg>")


def arrow_ne(x, y, color, style=""):
    return (f'<g transform="translate({x:.1f} {y:.1f})"><g class="b" style="{style}">'
            f'<path d="M0 8L8 0M2.5 0H8V5.5" fill="none" stroke="{color}" stroke-width="1.4" '
            f'stroke-linecap="round" stroke-linejoin="round"/></g></g>')


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load(p):
    with open(ROOT / p, encoding="utf-8") as f:
        return json.load(f)


def day(s):
    return dt.date.fromisoformat(s[:10])


def stats(days):
    counts = [d["count"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today isn't over: a quiet morning doesn't break the streak
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    months = defaultdict(int)
    for d in days:
        months[d["date"][:7]] += d["count"]
    keys = sorted(months)[-12:]
    return dict(total=sum(counts), active=sum(1 for c in counts if c), span=len(counts),
                longest=longest, current=current,
                busiest=max(counts, default=0),
                months=[(k, months[k]) for k in keys])


def levels_for(days):
    if all("level" in d for d in days):
        return [int(d["level"]) for d in days]
    nz = sorted(d["count"] for d in days if d["count"])
    if not nz:
        return [0] * len(days)
    q = [nz[min(int(len(nz) * f), len(nz) - 1)] for f in (.25, .5, .75)]
    return [0 if not d["count"] else 1 if d["count"] <= q[0] else 2 if d["count"] <= q[1]
            else 3 if d["count"] <= q[2] else 4 for d in days]


def mix(hex_a, hex_b, t):
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def ramp(accent):
    """Empty, then four steps of the accent: light tint up to a deeper shade."""
    return [EMPTY, mix(accent, "#ffffff", .75), mix(accent, "#ffffff", .5), accent, mix(accent, "#000000", .2)]


# --------------------------------------------------------------------------
# ASCII portrait
# --------------------------------------------------------------------------
CHARSET = " .:-=+*#%@"


def ascii_portrait(path, cols=120, rows=84):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    p = ROOT / path if path else None
    if not p or not p.exists():
        return None
    im = Image.open(p).convert("L")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    m = int(s * .015)  # trim the outer edge: screenshots and avatars often carry a grey border
    im = im.crop((m, m, s - m, s - m))
    small = im.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    # background = bright region flood-filled from top/left/right edges (keeps a white shirt)
    bg = [[False] * cols for _ in range(rows)]
    stack = [(x, 0) for x in range(cols)] + [(0, y) for y in range(rows)] + [(cols - 1, y) for y in range(rows)]
    while stack:
        x, y = stack.pop()
        if 0 <= x < cols and 0 <= y < rows and not bg[y][x] and px[x, y] > 215:
            bg[y][x] = True
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    fg = [px[x, y] for y in range(rows) for x in range(cols) if not bg[y][x]]
    lo, hi = (sorted(fg)[int(len(fg) * .02)], sorted(fg)[int(len(fg) * .98)]) if fg else (0, 255)
    out = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            if bg[y][x]:
                line += " "
                continue
            v = min(1, max(0, (px[x, y] - lo) / max(1, hi - lo)))  # 0 dark .. 1 light
            d = (1 - v) ** 1.5  # push mid-tones (skin) toward light glyphs so features read
            line += CHARSET[min(len(CHARSET) - 1, 1 + int(d * (len(CHARSET) - 1)))]
        out.append(line.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out, cols


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------
def card_hero(cfg):
    H = 432
    name = cfg["name"]
    c = Card(W, H, f"{' '.join(name)}. {cfg['tagline']}")
    acc = cfg.get("accent", "#2f55ff")
    c.add(f'<rect width="{W}" height="{H - GAP}" rx="14" fill="{PAPER}"/>')

    kick = cfg.get("kicker", "")
    c.add(f'<g style="{anim("fade", .9, 0, "ease-out")}">'
          f'<rect x="48" y="49" width="8" height="8" rx="2" fill="{acc}" style="{loop("pulse", 1.6, 0)}"/>'
          + c.text(66, 57, [(kick, MONO)], 12, MUTED, attrs=' letter-spacing="1"') + "</g>")

    left, avail = 44, 470
    size = min(116, min(avail / tw(l, SERIF_I if i else SERIF, 1) for i, l in enumerate(name)))
    y1, y2 = 190, 190 + size * .86
    c.add(c.text(left, y1, [(name[0], SERIF)], round(size, 1), INK, cls="b",
                 style=anim("rise", .8, .15), attrs=' letter-spacing="-2.5"'))
    # second line italic. The accent shine is a copy of it on top, filled with a gradient
    # whose only opaque part is the accent band, swept across by SMIL. It sits in a .smil
    # group, so reduced motion hides it and STATIC leaves it out.
    c.add(c.text(left, y2, [(name[1], SERIF_I)], round(size, 1), INK, cls="b",
                 style=anim("rise", .8, .3), attrs=' letter-spacing="-2.5"'))
    c.defs.append(f'<linearGradient id="shine" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="600" y2="0" '
                  f'gradientTransform="translate(-600 0)">'
                  f'<stop offset=".42" stop-color="{acc}" stop-opacity="0"/><stop offset=".5" stop-color="{acc}"/>'
                  f'<stop offset=".58" stop-color="{acc}" stop-opacity="0"/>'
                  + ("" if STATIC else
                     '<animateTransform attributeName="gradientTransform" type="translate" values="-600 0;600 0;600 0" '
                     'keyTimes="0;.45;1" dur="7s" begin="1.6s" repeatCount="indefinite"/>')
                  + "</linearGradient>")
    c.add(c.smil(c.text(left, y2, [(name[1], SERIF_I)], round(size, 1), "url(#shine)",
                        attrs=' letter-spacing="-2.5"')))

    ty = y2 + 46
    lines = wrap(cfg["tagline"], SANS, 18, 455, 3)
    c.add(f'<g class="b" style="{anim("rise", .8, .55)}">'
          + "".join(c.text(48, ty + i * 27, l, 18, BODY) for i, l in enumerate(lines)) + "</g>")
    link = cfg.get("link")
    if link:
        ly = ty + len(lines) * 27 + 4
        lw = tw(link["text"], MONO, 13)
        c.add(f'<g style="{anim("fade", .9, .8, "ease-out")}">' + c.text(48, ly, [(link["text"], MONO)], 13, INK)
              + arrow_ne(48 + lw + 10, ly - 9, acc, loop("nudgeup", 1.8, 1.6)) + "</g>")

    art = ascii_portrait(cfg.get("portrait"))
    if art:
        rows, cols = art
        box_w, box_h = 330, 340
        fs = min(box_w / (cols * .6), box_h / (len(rows) * 1.18))
        lh = fs * 1.18
        x0 = W - 44 - cols * .6 * fs
        y0 = 40 + (box_h - len(rows) * lh) / 2 + fs
        out = []
        for i, row in enumerate(rows):
            if not row.strip():
                continue
            c.chars[MONO].update(row)
            out.append(f'<text xml:space="preserve" x="{x0:.1f}" y="{y0 + i * lh:.1f}" font-family="{FAMILY["mono"]}" '
                       f'font-size="{fs:.2f}" fill="{INK}" style="{anim("fade", .35, .25 + i * .018, "ease-out")}">'
                       f"{escape(row)}</text>")
        c.add("<g>" + "".join(out) + "</g>")
    return c


def card_heatmap(cfg, data, st):
    days = data["days"]
    H = 257
    c = Card(W, H, f"Contribution graph: {st['total']:,} contributions in the last year")
    acc = cfg.get("accent", "#2f55ff")
    lv = ramp(acc)
    t0 = T["heatmap"]
    c.add(f'<rect width="{W}" height="{H - GAP}" rx="14" fill="{PAPER}"/>')
    a, b = cfg.get("heatmap_title", ["The year, ", "in blue"])
    c.add(c.text(42, 62, [(a, SERIF), (b, SERIF_I, acc)], 34, INK, cls="b", style=anim("rise", .8, t0)))
    c.add(c.text(W - 44, 60, [("REFRESHED DAILY", MONO)], 12, MUTED, anchor="end",
                 style=anim("fade", .9, t0, "ease-out"), attrs=' letter-spacing="1"'))

    levels = levels_for(days)
    first = day(days[0]["date"])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    cols = (day(days[-1]["date"]) - start).days // 7 + 1
    step = min(15, (W - 88) / cols)
    sz = step - 3
    x0, y0 = 44, 96
    rects, labels, seen = [], [], set()
    for d, l in zip(days, levels):
        dd = day(d["date"])
        k, r = (dd - start).days // 7, (dd.weekday() + 1) % 7
        x, y = x0 + k * step, y0 + r * step
        n = d["count"]
        rects.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{sz:.0f}" height="{sz:.0f}" rx="3" fill="{lv[l]}" '
                     f'class="c" style="{anim("pop", .4, t0 + .2 + k * .015 + r * .02, "ease-out")}">'
                     f'<title>{d["date"]}: {n} contribution{"" if n == 1 else "s"}</title></rect>')
        if r == 0 and dd.day <= 7 and k > 0 and (dd.year, dd.month) not in seen and x < W - 44 - 175:
            seen.add((dd.year, dd.month))
            labels.append(c.text(x, y0 + 7 * step + 16, [(f"{dd:%b}", MONO)], 11, MUTED))
    c.add("".join(rects))
    ly = y0 + 7 * step + 6
    lx = W - 44 - 5 * 14 - tw("more", MONO, 11) - 6
    leg = [c.text(lx - 8, ly + 10, [("less", MONO)], 11, MUTED, anchor="end")]
    leg += [f'<rect x="{lx + i * 14:.0f}" y="{ly:.0f}" width="11" height="11" rx="2.5" fill="{lv[i]}"/>' for i in range(5)]
    leg.append(c.text(lx + 5 * 14 + 3, ly + 10, [("more", MONO)], 11, MUTED))
    c.add(f'<g style="{anim("fade", .9, t0 + 1.6, "ease-out")}">' + "".join(labels + leg) + "</g>")
    return c


def card_activity(cfg, data, st):
    H = 352
    c = Card(W, H, f"{st['total']:,} contributions in the last year, {st['current']}-day streak")
    acc = cfg.get("accent", "#2f55ff")
    t0 = T["activity"]
    c.add(f'<rect width="{W}" height="{H - GAP}" rx="14" fill="{PAPER}"/>')
    c.add(c.text(40, 58, [("THE LAST 12 MONTHS ON GITHUB", MONO)], 12, MUTED,
                 style=anim("fade", .9, t0, "ease-out"), attrs=' letter-spacing="1"'))
    c.add(c.text(38, 114, [(f"{st['total']:,} ", SERIF), ("contributions", SERIF_I)], 52, INK,
                 cls="b", style=anim("rise", .8, t0 + .1)))

    months = st["months"]
    this_month = data["days"][-1]["date"][:7]
    best = max(range(len(months)), key=lambda k: months[k][1]) if months else -1
    maxv = max((v for _, v in months), default=0) or 1
    x0, x1, base, top = 40, 610, 292, 152
    slot = (x1 - x0) / max(len(months), 1)
    bw = slot * .8
    for k, (ym, v) in enumerate(months):
        x = x0 + k * slot
        h = max(4, (base - top) * v / maxv) if v else 3
        fill = acc if k == best and v else PENDING if ym == this_month else INK if v else RULE
        lab = f"{dt.date.fromisoformat(ym + '-01'):%b}"
        dl = t0 + .3 + k * .07
        c.add(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" fill="{fill}" '
              f'class="bot" style="{anim("grow", .8, dl)}"><title>{lab}: {v:,}</title></rect>')
        c.add(c.text(x + bw / 2, 314, [(lab, MONO)], 11, MUTED, anchor="middle", style=anim("fade", .9, dl, "ease-out")))
        if k == best and v:
            c.add(c.text(x + bw / 2, base - h - 10, [(f"{v:,}", MONO)], 11, acc, anchor="middle",
                         cls="c", style=anim("pop", .4, t0 + 1.3, "ease-out")))

    cur, lon = st["current"], st["longest"]
    streak_label = "current streak, and the longest" if cur and cur == lon else f"current streak · longest {lon}"
    stats_col = [
        ([(f"{cur} ", SERIF), ("day" if cur == 1 else "days", SERIF_I)], streak_label),
        ([(f"{st['active']}", SERIF), (f" / {st['span']}", SERIF, FAINT)], "days with a commit"),
        ([(f"{st['busiest']:,}", SERIF)], "on the busiest day"),
    ]
    for i, (runs, lab) in enumerate(stats_col):
        y = 104 + i * 92
        c.add(f'<g class="b" style="{anim("rise", .8, t0 + .7 + i * .15)}">' + c.text(650, y, runs, 40, INK)
              + c.text(650, y + 24, lab, 13, MUTED) + "</g>")
        if i < 2:
            c.add(f'<rect x="650" y="{y + 44}" width="190" height="1" fill="{RULE}" style="{anim("fade", .9, t0 + .7, "ease-out")}"/>')
    return c


def tile_value(tile, st, repos):
    v = tile.get("value")
    if v is None or isinstance(v, (int, float)):
        return v
    return {"total": st["total"], "active_days": st["active"], "longest_streak": st["longest"],
            "current_streak": st["current"], "busiest_day": st["busiest"],
            "public_repos": repos.get("public_repos", 0)}.get(v, 0)


def card_tile(i, tile, st, repos):
    w, H = TILE_W, 222
    rw, rh = w - 8, H - GAP
    color = tile.get("color", "#2f55ff")
    lum = sum(int(color[j:j + 2], 16) * f for j, f in ((1, .299), (3, .587), (5, .114))) / 255
    fg = INK if lum > .6 else "#ffffff"
    val = tile_value(tile, st, repos)
    unit = tile.get("unit", "")
    big = f"{val:,}" if val is not None else tile.get("big", "")
    c = Card(w, H, f"{tile.get('kicker', '')}: {big} {unit}. {tile.get('sub', '')}")
    t0 = T["tiles"] + i * .15

    c.defs.append(f'<clipPath id="card"><rect width="{rw:.3f}" height="{rh}" rx="14"/></clipPath>'
                  f'<clipPath id="slot"><rect x="0" y="62" width="{rw:.3f}" height="62"/></clipPath>'
                  '<linearGradient id="gl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                  '<stop offset=".5" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    g = [f'<g clip-path="url(#card)"><rect width="{rw:.3f}" height="{rh}" fill="{color}"/>'
         f'<circle class="c rg" style="{anim("ring", 1, t0 + .5, "ease-out")}" cx="{rw - 40:.1f}" cy="170" r="60" '
         f'fill="none" stroke="{fg}" stroke-opacity=".5" stroke-width="2"/>'
         f'<g transform="translate(-260 0)"><rect class="b sh" style="{loop("sheen", 5, t0 + 1.4)}" x="0" y="-20" '
         f'width="90" height="250" fill="url(#gl)"/></g></g>']
    g.append(c.text(24, 38, [(tile.get("kicker", ""), MONO)], 12, fg, cls="b",
                    style=anim("slidein", .6, t0 + .35), attrs=' letter-spacing="1.2"'))
    g.append(f'<g class="b" style="{anim("arrowin", .7, t0 + .5)}"><g class="b" style="{loop("nudge", 1.8, t0 + 1.3)}">'
             f'<path transform="translate({rw - 36:.1f} 28)" d="M0 5.5H10M6 1.5L10 5.5L6 9.5" fill="none" stroke="{fg}" '
             f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></g></g>')

    # number rolls up into a slot while it counts (SMIL frames; final value is a normal element)
    def big_text(s, attrs=""):
        return c.text(22, 112, [(f"{s} ", SERIF), (unit, SERIF_I)], 44, fg, attrs=attrs)

    size_fix = ""
    roll = []
    start = t0 + .45
    if isinstance(val, (int, float)) and val > 0:
        frames, step = 18, .061
        seq = [round(val * (1 - (1 - k / frames) ** 3)) for k in range(frames)]
        fr = []
        for k, v in enumerate(seq):
            tt = start + k * step
            fr.append(big_text(f"{v:,}", ' opacity="0"').replace(
                "</text>", f'<set attributeName="opacity" to="1" begin="{tt:.3f}s"/>'
                           f'<set attributeName="opacity" to="0" begin="{tt + step:.3f}s"/></text>'))
        roll.append(c.smil("".join(fr)))
        roll.append(big_text(big, f' style="{anim("show", .01, start + frames * step, "linear")}"'))
    else:
        roll.append(big_text(big))
    g.append(f'<g clip-path="url(#slot)"><g class="b" style="{anim("roll", .8, start, "cubic-bezier(.15,.8,.2,1)")}">'
             + "".join(roll) + "</g></g>" + size_fix)

    for j, line in enumerate(wrap(tile.get("sub", ""), SANS, 14, rw - 44, 3)):
        g.append(c.text(24, 150 + j * 20, line, 14, fg, cls="b", style=anim("rise", .8, t0 + .65 + j * .1),
                        attrs=' opacity=".92"'))
    c.add(f'<g class="tile" style="{anim("tilein", 1.1, t0, "cubic-bezier(.2,.8,.2,1)")}">' + "".join(g) + "</g>")
    return c


def card_title(text_runs, fill, label):
    H = 64
    c = Card(W, H, label)
    c.add(c.text(2, 46, text_runs, 34, fill, cls="b", style=anim("rise", .8, T["title"])))
    return c


DOTS = ["#2f55ff", "#ef3b2d", "#ffc81a"]


def card_repo(i, repo):
    w, H = TILE_W, 188
    rw = w - 8
    c = Card(w, H, f"{repo['name']}: {repo.get('description') or ''}")
    t0 = T["repos"] + i * .12
    g = [f'<rect width="{rw:.3f}" height="{H - GAP}" rx="14" fill="{PAPER}"/>',
         f'<rect x="24" y="30" width="8" height="8" rx="2" fill="{DOTS[i % 3]}"/>']
    size = 18
    while tw(repo["name"], SANS_B, size) > rw - 64 and size > 12:
        size -= .5
    g.append(c.text(40, 39, [(repo["name"], SANS_B)], size, INK))
    for j, line in enumerate(wrap(repo.get("description") or "No description yet.", SANS, 14, rw - 48, 3)):
        g.append(c.text(24, 72 + j * 21, line, 14, BODY))
    bits = [repo.get("language") or "code"]
    stars = repo.get("stars") or 0
    if stars:
        bits.append(f"★ {stars}")
    if repo.get("pushed_at"):
        d = day(repo["pushed_at"])
        bits.append(f"updated {d:%b} {d.day}")
    foot = "  ·  ".join(bits)
    if stars:  # Geist Mono has no star: draw that one glyph from Geist
        pre, post = foot.split("★")
        g.append(c.text(24, 152, [(pre, MONO), ("★", SANS), (post, MONO)], 12, MUTED, attrs=' xml:space="preserve"'))
    else:
        g.append(c.text(24, 152, [(foot, MONO)], 12, MUTED, attrs=' xml:space="preserve"'))
    c.add(f'<g class="b" style="{anim("rise", .8, t0)}">' + "".join(g) + "</g>")
    return c


# --------------------------------------------------------------------------
# README block and preview
# --------------------------------------------------------------------------
START, END = "<!-- cards:start -->", "<!-- cards:end -->"


def img(name, alt, width, href=None):
    tag = f'<img src="./cards/{name}.svg" width="{width}" alt="{escape(alt, {chr(34): "&quot;"})}" />'
    return f'<a href="{href}">{tag}</a>' if href else tag


def readme_block(cfg, st, repos_by_name):
    user = cfg["user"]
    gh = f"https://github.com/{user}"
    link = (cfg.get("link") or {}).get("href", gh)
    tiles = cfg.get("tiles", [])[:3]
    tile_imgs = "".join(
        img(f"tile-{i + 1}", f"{t.get('kicker', '')}: {t.get('unit', '')}", "33.333%", t.get("href"))
        for i, t in enumerate(tiles))
    repo_imgs = "".join(img(f"repo-{n}", n, "33.333%", f"{gh}/{n}") for n in cfg.get("featured", [])[:3])
    title = ('<picture><source media="(prefers-color-scheme: dark)" srcset="./cards/title-coding-dark.svg">'
             '<img src="./cards/title-coding-light.svg" width="100%" alt="What I\'m coding" /></picture>')
    lines = [
        '<div align="center">',
        img("hero", f"{' '.join(cfg['name'])}. {cfg['tagline']}", "100%", link) + "<br>",
        img("heatmap", "Contribution graph, refreshed daily", "100%") + "<br>",
        img("activity", "Contributions in the last 12 months, by month, with streak and busiest day", "100%") + "<br>",
        tile_imgs + "<br>",
        title + "<br>",
        repo_imgs,
        "</div>",
    ]
    foot = cfg.get("footer", [])
    if foot:
        lines += ['<p align="center">', " &nbsp;/&nbsp; ".join(f'<a href="{f["href"]}">{escape(f["text"])}</a>' for f in foot), "</p>"]
    return "\n".join(lines)


def write_readme(block):
    p = ROOT / "README.md"
    full = f"{START}\n{block}\n{END}"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if START in old and END in old:
        new = old[: old.index(START)] + full + old[old.index(END) + len(END):]
    else:
        new = full + "\n" + old
    p.write_text(new, encoding="utf-8")


def write_preview(block):
    """preview/{light,dark}.html: the README at GitHub's width, to screenshot in headless Chrome."""
    d = ROOT / "preview"
    d.mkdir(exist_ok=True)
    body = block.replace("./cards/", "../cards/")
    for theme, bg, fg in (("light", "#ffffff", "#0969da"), ("dark", "#0d1117", "#4493f8")):
        html = body
        if theme == "dark":
            html = re.sub(r'<source media="[^"]*" srcset="([^"]*)"><img src="[^"]*"', r'<img src="\1"', html)
        else:
            html = re.sub(r"<source [^>]*>", "", html)
        (d / f"{theme}.html").write_text(
            f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:{bg}">'
            f'<article style="width:880px;margin:24px auto;font:16px/1.5 system-ui">'
            f'<style>img{{max-width:100%;vertical-align:top}} a{{color:{fg}}}</style>{html}</article>', encoding="utf-8")


# --------------------------------------------------------------------------
def main():
    cfg = load("profile.json")
    data = load("data/contributions.json")
    repos = load("data/repos.json")
    data["days"] = sorted(data["days"], key=lambda d: d["date"])
    st = stats(data["days"])
    by_name = {r["name"]: r for r in repos.get("repos", [])}
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()

    cards = {"hero": card_hero(cfg), "heatmap": card_heatmap(cfg, data, st), "activity": card_activity(cfg, data, st)}
    for i, tile in enumerate(cfg.get("tiles", [])[:3]):
        cards[f"tile-{i + 1}"] = card_tile(i, tile, st, repos)
    title = [("What I'm ", SERIF), ("coding", SERIF_I)]
    cards["title-coding-light"] = card_title(title, INK, "What I'm coding")
    cards["title-coding-dark"] = card_title(title, "#e6edf3", "What I'm coding")
    for i, name in enumerate(cfg.get("featured", [])[:3]):
        cards[f"repo-{name}"] = card_repo(i, by_name.get(name, {"name": name}))

    for name, card in cards.items():
        (OUT / f"{name}.svg").write_text(card.svg(), encoding="utf-8")
        print(f"  {name + '.svg':<44} {(OUT / f'{name}.svg').stat().st_size / 1024:6.1f} KB")
    block = readme_block(cfg, st, by_name)
    write_readme(block)
    if STATIC:
        write_preview(block)
    print(f"{len(cards)} cards -> cards/" + ("  (STATIC)" if STATIC else ""))


if __name__ == "__main__":
    main()
