#!/usr/bin/env python3
"""Rasterize the splash CJK text into 1-bit bitmaps for Arduino_GFX drawBitmap."""
from PIL import Image, ImageDraw, ImageFont

TEXT = "创意开发"
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
W = H = 32
SIZE = 30
OUT = "/Volumes/Mac/develop/cli_dashboard/cjk_glyphs.h"

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
    f.write("static const uint8_t GLYPH_W = %d, GLYPH_H = %d, GLYPH_N = %d;\n" % (W, H, len(blobs)))
    for i, b in enumerate(blobs):
        f.write("static const uint8_t glyph_%d[%d] = {%s};\n" % (i, len(b), ",".join(str(x) for x in b)))
    f.write("static const uint8_t *const GLYPHS[%d] = {%s};\n" % (len(blobs), ",".join("glyph_%d" % i for i in range(len(blobs)))))

print("wrote %s: %d glyphs, %d bytes each" % (OUT, len(blobs), len(blobs[0])))
