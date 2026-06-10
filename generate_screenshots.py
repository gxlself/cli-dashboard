#!/usr/bin/env python3
"""Render PNG mockups of every dashboard display state for the README.

Run:  python3 generate_screenshots.py
Output: docs/screen_*.png  (640×344, 2× native resolution)
"""
import math, os
from PIL import Image, ImageDraw, ImageFont

# ── 1-bit glyph bitmaps decoded from cjk_glyphs.h / welcome_glyphs.h ─────────
# Each glyph is 32×32 pixels, 4 bytes per row, MSB = leftmost pixel.

GLYPH_W = GLYPH_H = 32  # "创意开发"
GLYPHS_DATA = [
    [0,0,0,0,0,0,0,0,0,16,0,120,0,60,0,48,0,56,0,48,0,124,0,48,0,127,15,48,0,231,134,48,1,193,230,48,3,128,230,48,7,128,70,48,15,0,6,48,15,255,134,48,5,255,134,48,1,129,134,48,1,129,134,48,1,129,134,48,1,129,134,48,1,131,134,48,1,159,134,48,1,143,6,48,1,136,6,48,1,128,70,48,1,128,96,48,1,128,224,48,1,129,224,48,1,255,192,112,0,255,131,240,0,0,1,192,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,3,128,0,0,7,128,0,0,3,128,0,15,255,255,192,15,255,255,192,0,16,32,0,0,120,28,0,0,56,56,0,31,255,255,240,31,255,255,240,0,0,0,0,1,255,255,0,1,255,255,0,1,128,3,0,1,128,3,0,1,255,255,0,1,255,255,0,1,128,3,0,1,255,255,0,1,255,255,0,0,0,128,0,0,67,128,128,7,57,193,192,6,49,140,224,14,48,14,112,14,56,60,40,28,63,252,0,0,15,192,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,7,255,255,240,7,255,255,240,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,0,28,14,0,31,255,255,252,31,255,255,252,0,28,14,0,0,28,14,0,0,60,14,0,0,56,14,0,0,56,14,0,0,112,14,0,0,240,14,0,1,224,14,0,3,192,14,0,15,128,14,0,31,0,14,0,2,0,14,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,3,192,0,1,3,134,0,0,195,143,0,1,227,135,128,1,131,3,128,3,131,1,0,3,7,0,16,7,255,255,240,7,255,255,240,2,14,0,0,0,14,0,0,0,12,0,0,0,31,255,192,0,63,255,128,0,56,3,128,0,124,7,0,0,252,7,0,1,238,14,0,3,199,30,0,7,131,252,0,31,1,248,0,62,0,240,0,12,3,254,0,0,31,159,252,1,255,7,248,3,248,1,240,0,224,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
]

WEL_W = WEL_H = 32  # "主人欢迎回来"
WEL_DATA = [
    [0,0,0,0,0,0,0,0,0,0,0,0,0,1,128,0,0,3,128,0,0,3,192,0,0,1,224,0,0,1,128,0,0,0,0,0,7,255,255,224,7,255,255,224,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,3,255,255,128,3,255,255,128,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,31,255,255,240,31,255,255,240,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,3,192,0,0,3,192,0,0,3,192,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,128,0,0,3,192,0,0,7,192,0,0,7,192,0,0,6,224,0,0,14,96,0,0,12,112,0,0,28,112,0,0,56,56,0,0,120,28,0,0,112,30,0,0,224,15,128,3,224,7,192,7,192,3,240,31,0,1,252,62,0,0,112,12,0,0,48,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,96,0,0,0,112,0,0,0,224,0,0,0,224,0,31,248,224,0,31,248,255,248,0,56,255,240,0,57,192,112,0,49,128,112,12,51,128,96,14,51,156,96,7,119,28,128,3,225,28,0,1,224,28,0,1,224,28,0,0,224,28,0,1,224,28,0,1,240,62,0,3,184,54,0,3,152,115,0,7,28,115,128,7,8,227,192,14,1,193,240,28,3,192,248,8,15,128,112,0,30,0,48,0,4,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,2,1,128,0,15,7,128,0,7,15,223,240,3,140,31,240,3,140,24,48,2,12,24,48,0,12,24,48,31,204,24,48,31,140,24,48,3,140,24,48,3,12,24,48,7,12,24,48,6,12,24,48,14,12,24,48,31,204,88,48,15,204,216,48,1,143,217,240,1,159,153,240,1,158,24,192,3,136,24,0,3,0,24,0,7,128,24,0,15,240,0,0,30,255,255,252,60,31,255,248,8,0,255,240,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,4,0,0,32,7,255,255,224,7,255,255,224,6,0,0,224,6,0,0,224,6,0,0,224,6,31,248,224,6,31,248,224,6,24,24,224,6,24,24,224,6,24,24,224,6,24,24,224,6,24,24,224,6,24,24,224,6,31,248,224,6,31,248,224,6,0,0,224,6,0,0,224,6,0,0,224,6,0,0,224,7,255,255,224,7,255,255,224,6,0,0,224,6,0,0,224,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,1,224,0,0,1,192,0,0,1,192,0,0,1,192,0,7,255,255,240,7,255,255,240,0,1,192,0,0,1,195,0,0,193,195,192,1,225,199,0,0,241,199,0,0,97,206,0,0,1,196,0,31,255,255,248,31,255,255,248,0,13,240,0,0,29,216,0,0,57,216,0,0,49,204,0,0,241,207,0,1,225,199,128,3,193,195,224,15,129,193,252,63,1,192,248,12,1,192,48,0,1,192,16,0,1,192,0,0,0,0,0,0,0,0,0,0,0,0,0],
]

def draw_glyph(d, data, x, y, w, h, color, scale=1):
    """Render a 1-bit GFX-format bitmap. MSB of each byte = leftmost pixel."""
    bpr = (w + 7) // 8  # bytes per row
    for row in range(h):
        for col in range(w):
            if data[row * bpr + col // 8] & (0x80 >> (col % 8)):
                px, py = x + col * scale, y + row * scale
                d.rectangle([px, py, px + scale - 1, py + scale - 1], fill=color)

SCALE = 2
W, H = 320 * SCALE, 172 * SCALE
OUTDIR = os.path.join(os.path.dirname(__file__), "docs")
os.makedirs(OUTDIR, exist_ok=True)

# ── colors ────────────────────────────────────────────────────────────────────
BLACK    = (  0,   0,   0)
WHITE    = (255, 255, 255)
GREEN    = (  0, 210,  70)
YELLOW   = (255, 215,   0)
CYAN     = (  0, 215, 215)
DARKGREY = ( 70,  70,  85)
NAVY     = ( 11,  22,  55)
GOLD     = (232, 196,  74)
PET      = (235, 140,  95)

# ── fonts ─────────────────────────────────────────────────────────────────────
_MONO = "/System/Library/Fonts/Monaco.ttf"
def font(size): return ImageFont.truetype(_MONO, int(size * SCALE))

SZ1 = font(8)    # textSize 1 (~6px native -> 8px at 2×)
SZ2 = font(13)   # textSize 2
SZ3 = font(18)   # textSize 3

# ── helpers ───────────────────────────────────────────────────────────────────
def s(v): return int(v * SCALE)   # scale a native coordinate

def new_canvas(bg=BLACK):
    img = Image.new("RGB", (W, H), bg)
    return img, ImageDraw.Draw(img)

def circle(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

def rrect(d, x, y, w, h, r, color):
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=color)

def hline(d, x, y, length, color):
    d.line([(x, y), (x + length, y)], fill=color, width=max(1, s(1)))

def text(d, x, y, txt, color, fnt=SZ2):
    d.text((x, y), txt, fill=color, font=fnt)

def text_w(txt, fnt=SZ2):
    bb = fnt.getbbox(txt)
    return bb[2] - bb[0]

def text_h(fnt=SZ2):
    bb = fnt.getbbox("Ag")
    return bb[3] - bb[1]

# ── pet character ─────────────────────────────────────────────────────────────
def draw_pet_working(d, cx, cy, f=8):
    """Typing pet (bob + paws on keyboard)."""
    bob = int(math.sin(f * 0.4) * s(2))
    by = cy + bob
    # ears
    circle(d, cx - s(16), by - s(20), s(6), PET)
    circle(d, cx + s(16), by - s(20), s(6), PET)
    # body
    rrect(d, cx - s(28), by - s(22), s(56), s(46), s(16), PET)
    # eyes
    circle(d, cx - s(11), by - s(3), s(4), BLACK)
    circle(d, cx + s(11), by - s(3), s(4), BLACK)
    circle(d, cx - s(12), by - s(4), s(1), WHITE)
    circle(d, cx + s(10), by - s(4), s(1), WHITE)
    # nose dot
    circle(d, cx, by + s(9), s(2), BLACK)
    # keyboard
    rrect(d, cx - s(18), by + s(26), s(36), s(7), s(2), DARKGREY)
    # paws tapping
    tap = 0 if (f % 8) < 4 else s(4)
    circle(d, cx - s(9), by + s(22) + tap, s(4), PET)
    circle(d, cx + s(9), by + s(22) + (s(4) - tap), s(4), PET)
    # typing dots
    d_count = (f // 4) % 4
    if d_count:
        text(d, cx + s(30), by - s(22), "." * d_count, CYAN, SZ2)

def draw_pet_idle(d, cx, cy, f=5):
    """Sleeping pet (closed eyes + z's)."""
    by = cy + s(2)
    # ears
    circle(d, cx - s(16), by - s(20), s(6), PET)
    circle(d, cx + s(16), by - s(20), s(6), PET)
    # body (slightly inflated — breathing)
    rrect(d, cx - s(28), by - s(20), s(56), s(44), s(16), PET)
    # closed eyes
    d.line([(cx - s(18), by - s(2)), (cx - s(7), by - s(2))],
           fill=BLACK, width=max(2, s(2)))
    d.line([(cx + s(7), by - s(2)), (cx + s(18), by - s(2))],
           fill=BLACK, width=max(2, s(2)))
    # sleepy mouth dot
    circle(d, cx, by + s(8), s(1), BLACK)
    # z's drifting up
    for k in range(3):
        prog = (f // 3 + k * 9) % 30
        zx = cx + s(24) + s(prog // 3)
        zy = by - s(16) - s(prog * 2)
        sz = SZ1 if prog < 15 else SZ2
        alpha = max(60, 255 - max(0, (prog - 20) * 30))
        col = (alpha, alpha, 255)
        text(d, zx, zy, "z", col, sz)

def draw_pet_done(d, cx, cy, f=3):
    """Celebrating pet (arms up + confetti)."""
    jump = int(abs(math.sin(f * 0.5)) * s(9))
    by = cy - jump
    shadow_w = max(s(6), s(24) - jump * 2)
    rrect(d, cx - shadow_w, cy + s(28), shadow_w * 2, s(5), s(2), (30, 35, 60))
    # arms raised
    rrect(d, cx - s(33), by - s(30), s(6), s(18), s(3), PET)
    rrect(d, cx + s(27), by - s(30), s(6), s(18), s(3), PET)
    # ears
    circle(d, cx - s(16), by - s(20), s(6), PET)
    circle(d, cx + s(16), by - s(20), s(6), PET)
    # body
    rrect(d, cx - s(28), by - s(22), s(56), s(46), s(16), PET)
    # happy eyes (upward arc lines)
    for ox in (-s(11), s(6)):
        d.arc([cx + ox - s(5), by - s(7), cx + ox + s(5), by + s(1)],
              start=200, end=340, fill=BLACK, width=max(2, s(2)))
    # open smile
    rrect(d, cx - s(8), by + s(6), s(16), s(7), s(3), BLACK)
    # confetti
    colors = [YELLOW, CYAN, GREEN]
    for i in range(6):
        px = cx - s(54) + ((i * 41 + f * 3) % s(108))
        py = by - s(26) + ((i * 19 + f * 2) % s(52))
        d.rectangle([px, py, px + s(3), py + s(3)], fill=colors[i % 3])

def draw_mini_pet(d, cx, cy, state="running", f=8):
    by = cy
    if state == "done":
        by = cy - int(abs(math.sin(f * 0.5)) * s(5))
    elif state == "running":
        by = cy + int(math.sin(f * 0.4) * s(2))
    circle(d, cx - s(9), by - s(11), s(3), PET)
    circle(d, cx + s(9), by - s(11), s(3), PET)
    rrect(d, cx - s(15), by - s(12), s(30), s(26), s(9), PET)
    if state == "idle":
        d.line([(cx - s(10), by - s(1)), (cx - s(4), by - s(1))],
               fill=BLACK, width=max(1, s(1)))
        d.line([(cx + s(4), by - s(1)), (cx + s(10), by - s(1))],
               fill=BLACK, width=max(1, s(1)))
        text(d, cx + s(13), by - s(12) - (f // 4) % s(8), "z", WHITE, SZ1)
    elif state == "done":
        # happy eyes
        for ox in (-s(6), s(3)):
            d.arc([cx + ox - s(3), by - s(4), cx + ox + s(3), by + s(2)],
                  start=200, end=340, fill=BLACK, width=max(1, s(1)))
        rrect(d, cx - s(4), by + s(4), s(8), s(4), s(2), BLACK)
        if (f // 4) % 2:
            text(d, cx - s(18), by - s(10), "+", YELLOW, SZ1)
    else:
        circle(d, cx - s(6), by - s(2), s(2), BLACK)
        circle(d, cx + s(6), by - s(2), s(2), BLACK)
        circle(d, cx, by + s(5), s(1), BLACK)
        d_count = (f // 4) % 4
        if d_count:
            text(d, cx + s(13), by - s(4), "." * d_count, CYAN, SZ1)

def channel_dots(d, view=0):
    gap = s(16)
    x0 = W - 3 * gap - s(10)
    y = H - s(12)
    for i in range(4):
        r = s(5) if i == view else s(3)
        col = WHITE if i == view else DARKGREY
        circle(d, x0 + i * gap, y, r, col)

def divider(d, y): hline(d, 0, s(y), W, DARKGREY)

def status_color(status):
    return {"running": GREEN, "done": YELLOW}.get(status, DARKGREY)

def channel_header(d, name, status, windows, view=0):
    sc = status_color(status)
    col = YELLOW if status == "done" else WHITE
    text(d, s(8), s(4), name, col, SZ3)
    dot_x = s(8) + text_w(name, SZ3) + s(10)
    circle(d, dot_x, s(16), s(5), sc)
    wc = "x%d" % windows
    text(d, W - text_w(wc, SZ3) - s(8), s(4), wc, CYAN if windows else DARKGREY, SZ3)
    divider(d, 32)

def bottom_bar(d, usage, view=0):
    divider(d, H // SCALE - 26)
    text(d, s(8), H - s(20), usage[:26] if usage else "-- no usage --",
         CYAN if usage else DARKGREY, SZ2)
    channel_dots(d, view)

# ── screens ───────────────────────────────────────────────────────────────────

def screen_working():
    img, d = new_canvas()
    channel_header(d, "Claude", "running", 2)
    draw_pet_working(d, W // 2, s(80), f=8)
    text(d, W // 2 - text_w("working", SZ2) // 2, s(120), "working", GREEN, SZ2)
    bottom_bar(d, "5h 42%  ctx 17%")
    return img

def screen_idle():
    img, d = new_canvas()
    channel_header(d, "Codex", "idle", 0)
    draw_pet_idle(d, W // 2, s(80), f=5)
    text(d, W // 2 - text_w("zzz", SZ2) // 2, s(120), "zzz", DARKGREY, SZ2)
    bottom_bar(d, "", view=1)
    return img

def screen_done():
    """Full-screen celebration."""
    img, d = new_canvas(NAVY)
    draw_pet_done(d, W // 2, s(70), f=3)
    text(d, W // 2 - text_w("DONE!", SZ3) // 2, s(116), "DONE!", YELLOW, SZ3)
    text(d, W // 2 - text_w("Claude", SZ2) // 2, s(148), "Claude", WHITE, SZ2)
    return img

def screen_multi():
    """Multiple sessions — grid of mini pets."""
    img, d = new_canvas()
    channel_header(d, "Claude", "running", 5)
    pets = ["running", "running", "idle", "idle", "idle"]
    n = len(pets)
    rows = 1 if n <= 3 else 2
    top = n if rows == 1 else (n + 1) // 2
    pitch = s(92)
    idx = 0
    for r in range(rows):
        k = top if r == 0 else (n - top)
        cy = s(62) if rows == 2 and r == 0 else (s(104) if r == 1 else s(80))
        startx = (W - (k - 1) * pitch) // 2
        for ci in range(k):
            draw_mini_pet(d, startx + ci * pitch, cy, pets[idx], f=8 + idx * 7)
            idx += 1
    bottom_bar(d, "5h 71%  ctx 22%")
    return img

def draw_badge(d, cx, cy):
    """Gold G badge ring."""
    r = s(22)
    circle(d, cx, cy, r, GOLD)
    circle(d, cx, cy, r - s(3), NAVY)
    circle(d, cx, cy, r - s(6), GOLD)
    text(d, cx - s(9), cy - s(11), "G", NAVY, SZ3)

def screen_sleep():
    """Mac display off — G badge + dim glyphs + floating z's."""
    img, d = new_canvas(NAVY)
    cx, cy = s(84), s(84)
    draw_badge(d, cx, cy)
    dim = (55, 60, 105)
    for i, gdata in enumerate(GLYPHS_DATA):
        draw_glyph(d, gdata, s(118) + i * s(36), s(68), GLYPH_W, GLYPH_H, dim, scale=SCALE)
    # floating Z's from badge
    for k, (ox, oy, sz, ch) in enumerate([
            (s(28),  -s(6),  SZ2, "Z"),
            (s(38), -s(18),  SZ1, "z"),
            (s(44), -s(28),  SZ1, "z"),
    ]):
        alpha = 210 - k * 30
        text(d, cx + ox, cy + oy, ch, (alpha, alpha, 255), sz)
    return img

def screen_boot():
    """Splash — G badge + typewriter 创意开发 (3 shown, cursor after 3rd)."""
    img, d = new_canvas(NAVY)
    cx, cy = s(84), s(84)
    draw_badge(d, cx, cy)
    # show 3 of 4 glyphs (mid-typewriter), cursor blinking after 3rd
    for i in range(3):
        draw_glyph(d, GLYPHS_DATA[i], s(118) + i * s(36), s(68), GLYPH_W, GLYPH_H, WHITE, scale=SCALE)
    # cursor after 3rd glyph
    cx3 = s(118) + 3 * s(36) - s(4)
    d.rectangle([cx3, s(68) + s(24), cx3 + s(14), s(68) + s(27)], fill=GOLD)
    return img

def screen_welcome():
    """Wake animation — 主人 / 欢迎回来 typewriter (all 6 shown)."""
    img, d = new_canvas(NAVY)
    # row 1: 主人 centered
    r1x = (320 - 2 * WEL_W) // 2
    for i in range(2):
        draw_glyph(d, WEL_DATA[i], s(r1x) + i * s(WEL_W), s(46), WEL_W, WEL_H, GOLD, scale=SCALE)
    # row 2: 欢迎回来 centered
    r2x = (320 - 4 * WEL_W) // 2
    for i in range(4):
        draw_glyph(d, WEL_DATA[2 + i], s(r2x) + i * s(WEL_W), s(94), WEL_W, WEL_H, WHITE, scale=SCALE)
    return img

# ── generate ──────────────────────────────────────────────────────────────────
SHOTS = [
    ("screen_working",  screen_working,  "Claude active — pet typing"),
    ("screen_idle",     screen_idle,     "All idle — pet sleeping"),
    ("screen_done",     screen_done,     "Task finished — celebration"),
    ("screen_multi",    screen_multi,    "Multiple sessions — mini-pet grid"),
    ("screen_sleep",    screen_sleep,    "Mac display off — sleep mode"),
    ("screen_boot",     screen_boot,     "Boot splash (typewriter mid-animation)"),
    ("screen_welcome",  screen_welcome,  "Wake animation — 主人欢迎回来"),
]

for name, fn, desc in SHOTS:
    path = os.path.join(OUTDIR, name + ".png")
    fn().save(path)
    print(f"  {name}.png  — {desc}")

print(f"\nAll screenshots saved to {OUTDIR}/")
