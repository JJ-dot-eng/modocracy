"""assets/icon.ico 생성 (hd2mm/web/icon.svg 와 같은 모양). Pillow 필요: python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
YELLOW = (255, 225, 26, 255)
DARK = (17, 19, 23, 255)


def scaled(points):
    return [(x * SIZE / 64, y * SIZE / 64) for x, y in points]


def chevron(draw, y, color):
    width = 6.5 * SIZE / 64
    draw.line(scaled([(19.5, y), (32, y + 12), (44.5, y)]), fill=color, width=round(width), joint="curve")


def main():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(scaled([(32, 2), (59, 17), (59, 47), (32, 62), (5, 47), (5, 17)]), fill=YELLOW)
    draw.polygon(scaled([(32, 9), (53, 20.8), (53, 43.2), (32, 55), (11, 43.2), (11, 20.8)]), fill=DARK)
    chevron(draw, 21.5, YELLOW)
    faded = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    chevron(ImageDraw.Draw(faded), 33.5, (255, 225, 26, 128))
    image = Image.alpha_composite(image, faded)
    out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    image.resize((256, 256), Image.LANCZOS).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
