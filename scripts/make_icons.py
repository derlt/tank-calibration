"""Draw the app icons of site/app/ (run by hand when the icon changes).

    uv run --with pillow python scripts/make_icons.py

The same shapes as site/app/icon.svg, on a 512 grid, drawn at 4x and reduced.
The icons have no transparency (iOS fills transparency with black), and the
picture stays inside the middle 80 % (the maskable safe zone).
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "site" / "app"
BRAND, WATER, WHITE = (20, 50, 74), (114, 180, 236), (255, 255, 255)


def draw(size: int) -> Image.Image:
    k = size * 4 / 512
    big = Image.new("RGB", (size * 4, size * 4), BRAND)
    d = ImageDraw.Draw(big)

    def box(x0, y0, x1, y1):
        return [x0 * k, y0 * k, x1 * k, y1 * k]

    # the water, clipped to the inside of the tank
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box(105, 199, 407, 321), radius=61 * k, fill=255)
    water = Image.new("L", big.size, 0)
    ImageDraw.Draw(water).rectangle(box(105, 250, 407, 330), fill=255)
    big.paste(WATER, mask=Image.composite(water, Image.new("L", big.size, 0), mask))
    d.rounded_rectangle(box(96, 190, 416, 330), radius=70 * k, outline=WHITE, width=round(18 * k))
    d.line([330 * k, 105 * k, 330 * k, 290 * k], fill=WHITE, width=round(14 * k))
    d.line([330 * k, 250 * k, 352 * k, 250 * k], fill=WHITE, width=round(10 * k))
    for x, y in ((330, 105), (330, 290)):   # round line ends
        d.ellipse(box(x - 7, y - 7, x + 7, y + 7), fill=WHITE)
    return big.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512)):
        draw(size).save(OUT / name, optimize=True)
        print(name, size)
