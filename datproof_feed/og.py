"""The picture shown when someone shares the home page: 1200x630 PNG in the page's own dithered look,
with the headline, today's yields for STRC, SATA and SATS, and the date they are true for.

    python -m datproof_feed.og                  # reads site/v1, writes site/og.png
    python -m datproof_feed.og --fetch-fonts    # first gets the headline face from Fontshare
    python -m datproof_feed.og --dry-run        # renders and checks, writes to a temp folder

Type: Gambetta Light for the name and headline, as on the page, and Sora for the figures. Sora (SIL
Open Font License) is committed in assets/fonts/. Gambetta's licence does not allow it in a public
repository, so --fetch-fonts downloads the official copy from Fontshare into .cache/fonts/ (ignored by
git) for this run only; without it the picture is not built.

Everything is rendered and checked in memory first. On any failure site/og.png is left as it was
(yesterday's picture stays up) and the exit code is 1. The same feed always gives the same bytes, so a
second run changes nothing.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import pathlib
import sys
import tempfile
import urllib.request
import zipfile

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
FONTS = ROOT / "assets" / "fonts"
CACHE = ROOT / ".cache" / "fonts"
SORA = FONTS / "Sora[wght].ttf"
GAMBETTA = {"light": "Gambetta-Light.otf", "italic": "Gambetta-LightItalic.otf"}
GAMBETTA_ZIP = "https://api.fontshare.com/v2/fonts/download/gambetta"
W, H = 1200, 630
OUT = "og.png"


# ---------- colours: the page's green tokens (site/next/styles.css), oklch -> sRGB ----------

def oklch(l: float, c: float, h: float) -> tuple[int, int, int]:
    a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    l_, m_, s_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3, (l - 0.1055613458 * a - 0.0638541728 * b) ** 3, \
        (l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def gamma(x: float) -> int:
        x = min(1.0, max(0.0, x))
        return round(255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055))
    return tuple(gamma(x) for x in rgb)  # type: ignore[return-value]


BG = oklch(0.155, 0.014, 162)
LINE = oklch(0.275, 0.018, 162)
INK = oklch(0.965, 0.008, 155)
INK2 = oklch(0.8, 0.014, 158)
INK3 = oklch(0.69, 0.016, 158)
ACCENT = oklch(0.85, 0.18, 148)   # --accent-ink, the range in the headline
DOT = oklch(0.36, 0.1, 150)       # --dither
DOT_ACC = oklch(0.8, 0.2, 148)    # --accent, the brightest dots in the corner
DOT_MID = tuple(round(DOT[i] + (DOT_ACC[i] - DOT[i]) * 0.38) for i in range(3))


class OgError(Exception):
    pass


# ---------- fonts ----------

def fetch_fonts(cache: pathlib.Path = CACHE) -> None:
    """Download the official Gambetta package from Fontshare and keep the two light faces in cache."""
    if all((cache / f).exists() for f in GAMBETTA.values()):
        return
    req = urllib.request.Request(GAMBETTA_ZIP, headers={"User-Agent": "datproof-og"})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    cache.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for want in GAMBETTA.values():
            name = next((n for n in z.namelist() if n.endswith("/OTF/" + want)), None)
            if not name:
                raise OgError(f"{want} not in the Fontshare package")
            (cache / want).write_bytes(z.read(name))


def faces(cache: pathlib.Path = CACHE, sora: pathlib.Path = SORA, display: pathlib.Path | None = None):
    """Font loader. `display` swaps Gambetta for another file (the tests use Sora, offline)."""
    from PIL import ImageFont

    disp = {k: (display or cache / f) for k, f in GAMBETTA.items()}
    for p in [sora, *disp.values()]:
        if not p.exists():
            raise OgError(f"font missing: {p.name} (run with --fetch-fonts)")

    def text(size: int, weight: int):
        f = ImageFont.truetype(str(sora), size)
        f.set_variation_by_axes([weight])
        return f
    return {"disp": lambda size: ImageFont.truetype(str(disp["light"]), size),
            "ital": lambda size: ImageFont.truetype(str(disp["italic"]), size),
            "text": text}


# ---------- what the picture says, from the feed ----------

def content(feed: dict) -> dict:
    rows = []
    for t in pages.LEAD:  # all three or no picture: the page never shows a favourite
        i = pages.inst(feed, t)
        if not i:
            raise OgError(f"{t} is not in the feed")
        y = pages.val(i.get("yield_pct"))
        if y is None:
            raise OgError(f"{i['ticker']} has no yield today ({pages.reason(i.get('yield_pct'))})")
        rows.append({"t": i["ticker"], "y": pages.pct(y), "issuer": i.get("issuer") or ""})
    pd = pages.price_date(feed)
    if not pd:
        raise OgError("the feed has no price date")
    return {"range": pages.hl_range(feed), "rows": rows, "date": f"Yields at the {pages.day(pd)} close"}


# ---------- drawing ----------

BAYER = [[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26], [12, 44, 4, 36, 14, 46, 6, 38],
         [60, 28, 52, 20, 62, 30, 54, 22], [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
         [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]
CELL = 3  # px per dot cell: about the page's dot size, still dots (not a blur) in a small preview


def dither(img) -> None:
    """The page's backdrop: ordered 8x8 dots, densest in the top-right corner, fading out to the left."""
    px = img.load()
    cx, cy = W * 1.02, -H * 0.12
    for gy in range(0, H, CELL):
        for gx in range(0, W, CELL):
            d = math.hypot((gx - cx) / (W * 0.62), (gy - cy) / (H * 1.05))
            v = max(0.0, 1.0 - d) ** 1.25
            # a slow ripple so the field has shape, as the page's moving field does in a still frame
            v *= 0.82 + 0.18 * math.sin(gx * 0.011 + gy * 0.017) * math.cos(gy * 0.009 - gx * 0.004)
            t = (BAYER[(gy // CELL) & 7][(gx // CELL) & 7] + 0.5) / 64
            if v <= t:
                continue
            col = DOT_ACC if v > t + 0.62 else DOT_MID if v > t + 0.3 else DOT
            for yy in range(gy, min(gy + CELL - 1, H)):
                for xx in range(gx, min(gx + CELL - 1, W)):
                    px[xx, yy] = col


def render(feed: dict, fonts=None) -> bytes:
    from PIL import Image, ImageDraw

    c = content(feed)
    f = fonts or faces()
    img = Image.new("RGB", (W, H), BG)
    dither(img)
    d = ImageDraw.Draw(img)
    x0 = 72

    d.text((x0, 58), "DATproof", font=f["disp"](38), fill=INK)

    # headline, two lines as on the page: "Earn 12–17% on / your idle cash."
    size, top, gap = 104, 150, 112
    disp, ital = f["disp"](size), f["ital"](size)
    x = x0
    for word, font, fill in (("Earn ", disp, INK), (c["range"], ital, ACCENT), (" on", disp, INK)):
        d.text((x, top), word, font=font, fill=fill)
        x += d.textlength(word, font=font)
    line1 = x
    d.text((x0, top + gap), "your idle cash.", font=disp, fill=INK)
    if line1 > W - x0:
        raise OgError(f"the headline is {line1 - x0:.0f}px wide and would not fit")

    # three figures, same size and order, no favourite; a rule above them
    ry = 448
    d.line([(x0, ry), (W - x0, ry)], fill=LINE, width=1)
    col = (W - 2 * x0) // 3
    tk, yl, iss = f["text"](26, 600), f["text"](58, 300), f["text"](22, 400)
    for n, r in enumerate(c["rows"]):
        cx = x0 + n * col
        d.text((cx, ry + 26), r["t"], font=tk, fill=INK)
        d.text((cx + d.textlength(r["t"], font=tk) + 12, ry + 30), r["issuer"], font=iss, fill=INK3)
        d.text((cx, ry + 62), r["y"], font=yl, fill=INK)
        d.text((cx + d.textlength(r["y"], font=yl) + 10, ry + 92), "a year", font=iss, fill=INK2)
    small = f["text"](20, 400)
    d.text((W - x0 - d.textlength(c["date"], font=small), 70), c["date"], font=small, fill=INK2)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def check(png: bytes) -> None:
    from PIL import Image

    im = Image.open(io.BytesIO(png))
    if im.size != (W, H) or im.format != "PNG":
        raise OgError(f"picture is {im.format} {im.size}, not PNG {(W, H)}")
    if len(png) > 1_000_000:
        raise OgError(f"picture is {len(png)} bytes; link previews want it under 1 MB")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.og")
    ap.add_argument("--dry-run", action="store_true", help="render and check; write to a temp folder")
    ap.add_argument("--fetch-fonts", action="store_true", help="download Gambetta from Fontshare first")
    ap.add_argument("--site", default=str(SITE))
    args = ap.parse_args(argv)
    site = pathlib.Path(args.site)
    try:
        if args.fetch_fonts:
            fetch_fonts()
        png = render(pages.load(site / "v1"))
        check(png)
    except Exception as err:  # any failure keeps yesterday's picture
        print(f"picture not written ({type(err).__name__}: {err}); yesterday's picture stays up", file=sys.stderr)
        return 1
    dest = pathlib.Path(tempfile.mkdtemp(prefix="datproof-og-")) if args.dry_run else site
    p = dest / OUT
    if p.exists() and p.read_bytes() == png:
        print(f"picture: unchanged, in {dest}")
        return 0
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(png)
    os.replace(tmp, p)
    print(f"picture: {len(png)} bytes written, in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
