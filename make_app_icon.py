"""
סקריפט חד-פעמי - יוצר קובץ tamlel.ico לשימוש בקיצור על שולחן העבודה.
משתמש באותה צורה כמו האייקון ב-tray (אות t עם hook בתחתית).

הרצה:
    python make_app_icon.py
"""

from PIL import Image, ImageDraw


def make_t_image(size, color="#1ea84a"):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    stem_x1 = int(s * 0.31)
    stem_x2 = int(s * 0.52)
    stem_y_top = int(s * 0.15)
    stem_y_curve = int(s * 0.62)

    cb_x1 = stem_x2
    cb_x2 = int(s * 0.74)
    cb_y1 = int(s * 0.38)
    cb_y2 = int(s * 0.57)

    hook_right = int(s * 0.62)
    hook_bottom = int(s * 0.85)

    draw.rectangle([stem_x1, stem_y_top, stem_x2, stem_y_curve], fill=color)
    draw.rectangle([cb_x1, cb_y1, cb_x2, cb_y2], fill=color)

    hook_h = hook_bottom - stem_y_curve
    box = [stem_x1, stem_y_curve - hook_h, hook_right, stem_y_curve + hook_h]
    draw.pieslice(box, 0, 180, fill=color)
    return img


def main():
    sizes = [16, 32, 48, 64, 128, 256]
    images = [make_t_image(s) for s in sizes]
    images[0].save(
        "tamlel.ico",
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[1:],
    )
    print("Created tamlel.ico with sizes:", sizes)


if __name__ == "__main__":
    main()
