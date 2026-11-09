"""Генерация PNG-иконок PWA (простой минималистичный силуэт автомобиля на тёмном фоне).
Запуск: python scripts/gen-icons.py (нужен Pillow). Внешние сервисы не используются."""
from pathlib import Path

from PIL import Image, ImageDraw

BG = (17, 24, 39, 255)       # #111827
FG = (255, 255, 255, 255)
SS = 4                        # суперсэмплинг для сглаживания


def car(size: int, scale: float, bg_opaque: bool = True) -> Image.Image:
    """scale — доля холста, занимаемая силуэтом (для maskable меньше, чтобы попасть в безопасную зону)."""
    s = size * SS
    img = Image.new("RGBA", (s, s), BG)
    d = ImageDraw.Draw(img)
    w = s * scale
    ox = (s - w) / 2
    oy = s / 2 - w * 0.22

    def p(x: float, y: float) -> tuple[float, float]:
        return ox + x * w, oy + y * w

    # кузов (вид сбоку): крыша и капот/багажник
    body = [p(0.00, 0.30), p(0.06, 0.22), p(0.24, 0.20), p(0.34, 0.04), p(0.68, 0.04),
            p(0.80, 0.20), p(0.95, 0.24), p(1.00, 0.34), p(1.00, 0.46), p(0.00, 0.46)]
    d.polygon(body, fill=FG)
    # окна
    d.polygon([p(0.37, 0.09), p(0.49, 0.09), p(0.49, 0.20), p(0.30, 0.20)], fill=BG)
    d.polygon([p(0.53, 0.09), p(0.66, 0.09), p(0.74, 0.20), p(0.53, 0.20)], fill=BG)
    # колёса
    for cx in (0.22, 0.78):
        x, y = p(cx, 0.46)
        r = w * 0.095
        d.ellipse([x - r * 1.25, y - r * 1.25, x + r * 1.25, y + r * 1.25], fill=BG)
        d.ellipse([x - r, y - r, x + r, y + r], fill=FG)
        r2 = r * 0.42
        d.ellipse([x - r2, y - r2, x + r2, y + r2], fill=BG)
    out = img.resize((size, size), Image.LANCZOS)
    return out if not bg_opaque else out.convert("RGB")


def main() -> None:
    pub = Path(__file__).resolve().parent.parent / "public"
    car(192, 0.62).save(pub / "icon-192.png", optimize=True)
    car(512, 0.62).save(pub / "icon-512.png", optimize=True)
    # maskable: значимое содержимое внутри центрального круга диаметром 80% (безопасная зона)
    car(512, 0.50).save(pub / "icon-512-maskable.png", optimize=True)
    car(180, 0.62).save(pub / "apple-touch-icon.png", optimize=True)  # непрозрачная, iOS сама скругляет
    print("icons generated in", pub)


if __name__ == "__main__":
    main()
