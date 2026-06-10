#!/usr/bin/env python3
"""Rasterize welcome message CJK glyphs into 1-bit bitmaps."""
from PIL import Image, ImageDraw, ImageFont

TEXT = "主人欢迎回来"
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
W = H = 32
SIZE = 30
OUT = "/Volumes/Mac/develop/cli_dashboard/welcome_glyphs.h"

font = ImageFont.truetype(FONT, SIZE)
blobs = []
for ch in TEXT:
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), ch, font=font)
    x = (W - (bb[2] - bb[0])) // 2 - bb[0]
    y = (H - (bb[3] - bb[1])) // 2 - bb[1]
    d.text((x, y), ch, font=font, fill=255)
    blobs.append(img.tobytes())

with open(OUT, "w") as f:
    f.write("// auto-generated 1-bit glyphs for: %s\n#pragma once\n#include <stdint.h>\n" % TEXT)
    f.write("static const uint8_t WEL_W = %d, WEL_H = %d, WEL_N = %d;\n" % (W, H, len(blobs)))
    for i, b in enumerate(blobs):
        f.write("static const uint8_t wel_glyph_%d[%d] = {%s};\n" % (i, len(b), ",".join(str(x) for x in b)))
    f.write("static const uint8_t *const WEL_GLYPHS[%d] = {%s};\n" % (
        len(blobs), ",".join("wel_glyph_%d" % i for i in range(len(blobs)))))

print("wrote %s: %d glyphs (%s)" % (OUT, len(blobs), TEXT))
