"""
מייצר סרטון/GIF להדגמת אנימציית ה-overlay של Tamlel.
מרנדר כל פריים ב-PIL עם אותם קבועים של overlay.py - כולל:
  - אנימציית פתיחה (ease_out_back, ~280ms)
  - שלב recording עם ברים רוקדים (~2 שניות)
  - שלב processing: הברים הימניים מתחבאים, ספינר מסתובב (~1.5 שניות)
  - אנימציית סגירה (ease_in_back, ~200ms)

פלט:
  media/demo.gif   - תאימות אוניברסלית, רקע שקוף קשה (1-bit)
  media/demo.png   - APNG עם אלפא מלא (קצוות חלקים)
"""
import os
import math
import random
from PIL import Image, ImageDraw

# ---------- קבועים זהים ל-overlay.py ----------
NUM_BARS = 14
BAR_WIDTH = 3
BAR_GAP = 2
BAR_MIN_HEIGHT = 3
PILL_HEIGHT = 26
WINDOW_HEIGHT = 34
PADDING_X = 12
PILL_OUTLINE_WIDTH = 2
SPINNER_SIZE = 14
SPINNER_MARGIN_RIGHT = 4
SPINNER_GAP_FROM_BARS = 4
SPINNER_ARC_EXTENT = 90
SPINNER_WIDTH = 2
SPINNER_ROT_PER_FRAME = 18
OVERSHOOT_PAD_X = 14
OVERSHOOT_PAD_Y = 6

bars_width_full = NUM_BARS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
TARGET_PILL_W = PADDING_X * 2 + bars_width_full       # 91
TARGET_PILL_H = WINDOW_HEIGHT                          # 34
CANVAS_W = TARGET_PILL_W + OVERSHOOT_PAD_X            # 105
CANVAS_H = TARGET_PILL_H + OVERSHOOT_PAD_Y            # 40
PILL_OFF_X = OVERSHOOT_PAD_X // 2                     # 7

bar_positions = [
    (PILL_OFF_X + PADDING_X + i * (BAR_WIDTH + BAR_GAP),
     PILL_OFF_X + PADDING_X + i * (BAR_WIDTH + BAR_GAP) + BAR_WIDTH)
    for i in range(NUM_BARS)
]
SPINNER_LEFT = (PILL_OFF_X + TARGET_PILL_W - PADDING_X
                - SPINNER_MARGIN_RIGHT - SPINNER_SIZE)
NUM_BARS_VISIBLE_PROC = sum(
    1 for x0, x1 in bar_positions
    if x1 <= SPINNER_LEFT - SPINNER_GAP_FROM_BARS
)

# צבעים (RGBA). פיל באלפא מלא - כשמייצאים ל-GIF ועושים composite מעל
# רקע מגנטה, אלפא חלקי דולף לתוך הצבע ויוצר גוון סגלגל. בדמו זה לא קריטי
# שיהיה שקוף-חלקית כמו ב-overlay האמיתי.
PILL_FILL = (26, 26, 26, 255)
PILL_OUTLINE = (255, 255, 255, 255)
BAR_COLOR = (255, 255, 255, 255)
SPINNER_COLOR = (255, 255, 255, 255)
TRANSPARENT_BG = (0, 0, 0, 0)

# רינדור: מציירים גדול ומקטינים לאנטי-אליאסינג איכותי
SUPERSAMPLE = 4    # פי כמה לרנדר פנימי
DISPLAY_SCALE = 4  # פי כמה הפלט הסופי מעל הגודל הלוגי

OUT_W = CANVAS_W * DISPLAY_SCALE
OUT_H = CANVAS_H * DISPLAY_SCALE
BIG_W = CANVAS_W * DISPLAY_SCALE * SUPERSAMPLE
BIG_H = CANVAS_H * DISPLAY_SCALE * SUPERSAMPLE
S = DISPLAY_SCALE * SUPERSAMPLE  # סקיילר ממידות לוגיות לפיקסלי big


# ---------- easing ----------
def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_in_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return c3 * t ** 3 - c1 * t ** 2


# ---------- ציור הפיל ----------
def draw_pill(d, pw, ph):
    """מצייר פיל בגודל pw x ph ממורכז בקנבס."""
    if pw < 4 or ph < 4:
        return
    pill_h_visual = max(2, pw * 0 + ph * PILL_HEIGHT / TARGET_PILL_H)
    inset_x = max(1, 2 * ph / TARGET_PILL_H)
    pw_total = pw - 2 * inset_x
    if pw_total < 4:
        return

    cx = CANVAS_W / 2
    cy = CANVAS_H / 2
    left = cx - pw_total / 2
    right = left + pw_total
    top = cy - pill_h_visual / 2
    bot = top + pill_h_visual
    r = min(pill_h_visual / 2, pw_total / 2)
    if r < 1:
        return

    ow = max(1, PILL_OUTLINE_WIDTH * S)

    # ---------- מילוי ----------
    d.ellipse([left * S, top * S, (left + 2 * r) * S, bot * S],
              fill=PILL_FILL)
    d.ellipse([(right - 2 * r) * S, top * S, right * S, bot * S],
              fill=PILL_FILL)
    if right - r > left + r:
        d.rectangle([(left + r) * S, top * S, (right - r) * S, bot * S],
                    fill=PILL_FILL)

    # ---------- outline ----------
    # PIL: arc הולך CW מ-start ל-end; 0° = שעה 3.
    # חצי שמאלי: מ-90° (למעלה) ל-270° (למטה) דרך 180° (שמאל)
    d.arc([left * S, top * S, (left + 2 * r) * S, bot * S],
          start=90, end=270, fill=PILL_OUTLINE, width=int(ow))
    # חצי ימני: מ-270° (למטה) ל-90° (למעלה) דרך 0° (ימין)
    d.arc([(right - 2 * r) * S, top * S, right * S, bot * S],
          start=270, end=90, fill=PILL_OUTLINE, width=int(ow))
    if right - r > left + r:
        d.line([(left + r) * S, top * S, (right - r) * S, top * S],
               fill=PILL_OUTLINE, width=int(ow))
        d.line([(left + r) * S, bot * S, (right - r) * S, bot * S],
               fill=PILL_OUTLINE, width=int(ow))


def draw_bars(d, levels, n_visible):
    cy = CANVAS_H / 2
    max_h = PILL_HEIGHT - 6
    min_h = BAR_MIN_HEIGHT
    for i, (x0, x1) in enumerate(bar_positions):
        if i >= n_visible:
            continue
        lvl = levels[i] if i < len(levels) else 0
        h = min_h + lvl * (max_h - min_h)
        y0 = cy - h / 2
        y1 = cy + h / 2
        # קצוות מעוגלים קלים על הברים
        d.rounded_rectangle(
            [x0 * S, y0 * S, x1 * S, y1 * S],
            radius=max(1, (BAR_WIDTH / 2) * S),
            fill=BAR_COLOR,
        )


def draw_spinner(d, angle):
    cy = CANVAS_H / 2
    r = SPINNER_SIZE / 2
    cx = SPINNER_LEFT + r
    sw = max(1, SPINNER_WIDTH * S)
    # ב-tkinter: extent CCW מהזווית; ב-PIL: end CW. נשמור על האשליה של סיבוב
    # ע"י המרת זווית: PIL_start = -angle, PIL_end = PIL_start + EXTENT
    pil_start = (-angle) % 360
    pil_end = pil_start + SPINNER_ARC_EXTENT
    d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S],
          start=pil_start, end=pil_end, fill=SPINNER_COLOR, width=int(sw))


def render_frame(pw, ph, levels, n_bars_visible, spinner_visible, spinner_angle):
    big = Image.new("RGBA", (BIG_W, BIG_H), TRANSPARENT_BG)
    d = ImageDraw.Draw(big)
    draw_pill(d, pw, ph)
    if n_bars_visible > 0:
        draw_bars(d, levels, n_bars_visible)
    if spinner_visible:
        draw_spinner(d, spinner_angle)
    # downsample לאנטי-אליאסינג
    out = big.resize((OUT_W, OUT_H), Image.LANCZOS)
    return out


# ---------- בניית טיימליין ----------
def build_frames():
    FRAME_MS = 33  # ~30 fps
    frames = []
    durations = []

    random.seed(42)
    sw, sh = TARGET_PILL_H * 6 // 10, TARGET_PILL_H * 6 // 10

    # --- שלב 0: שנייה של פריימים ריקים (נשימה בין לופים) ---
    blank_frame = Image.new("RGBA", (OUT_W, OUT_H), TRANSPARENT_BG)
    # פריים בודד בן 1000ms במקום ~30 פריימים נפרדים - חוסך גודל קובץ
    frames.append(blank_frame)
    durations.append(1000)

    # --- שלב 1: פתיחה ---
    open_steps = max(1, 280 // FRAME_MS)
    for i in range(open_steps + 1):
        t = i / open_steps
        e = ease_out_back(t)
        pw = sw + (TARGET_PILL_W - sw) * e
        ph = sh + (TARGET_PILL_H - sh) * e
        frames.append(render_frame(pw, ph, [0] * NUM_BARS, 0, False, 0))
        durations.append(FRAME_MS)

    # --- שלב 2: recording עם ברים ---
    # מדמים גל קולי: לכל בר רמה שמתפתחת לאט עם רעש
    levels = [0.0] * NUM_BARS
    rec_frames = 70
    for i in range(rec_frames):
        # רמה חדשה לפי גל סינוס + רעש
        new_levels = []
        for j in range(NUM_BARS):
            base = 0.5 + 0.4 * math.sin(i * 0.25 + j * 0.5)
            noise = (random.random() - 0.5) * 0.4
            target = max(0.05, min(1.0, base + noise))
            # החלקה
            smoothed = levels[j] + (target - levels[j]) * 0.45
            new_levels.append(smoothed)
        levels = new_levels
        frames.append(render_frame(
            TARGET_PILL_W, TARGET_PILL_H, levels, NUM_BARS, False, 0))
        durations.append(FRAME_MS)

    # --- מעבר: ברים נחים, ספינר מופיע ---
    # (אין צורך בפריימי מעבר - המעבר עצמו מיידי באפליקציה)
    spin_frames = 60
    spinner_angle = 0
    for i in range(spin_frames):
        spinner_angle = (spinner_angle - SPINNER_ROT_PER_FRAME) % 360
        frames.append(render_frame(
            TARGET_PILL_W, TARGET_PILL_H, [0] * NUM_BARS,
            NUM_BARS_VISIBLE_PROC, True, spinner_angle))
        durations.append(FRAME_MS)

    # --- שלב 3: סגירה ---
    close_steps = max(1, 200 // FRAME_MS)
    for i in range(close_steps + 1):
        t = i / close_steps
        e = ease_in_back(t)
        pw = TARGET_PILL_W + (sw - TARGET_PILL_W) * e
        ph = TARGET_PILL_H + (sh - TARGET_PILL_H) * e
        # gating: אם e יוצא ממש שלילי (משיכה אחורה) - לפעמים pw יוצא שלילי.
        # render_frame כבר מטפל בזה (חוזר ריק).
        frames.append(render_frame(pw, ph, [0] * NUM_BARS, 0, False, 0))
        durations.append(FRAME_MS)

    # פריים סיום ריק (כדי שיהיה ברור שהסתיים בלולאה)
    frames.append(Image.new("RGBA", (OUT_W, OUT_H), TRANSPARENT_BG))
    durations.append(400)

    return frames, durations


# ---------- שמירה ----------
def save_apng(frames, durations, path):
    """שומר APNG עם אלפא מלא (קצוות חלקים)."""
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
        format="PNG",
    )
    print(f"  APNG: {path} ({len(frames)} frames, "
          f"{os.path.getsize(path)//1024} KB)")


def save_gif(frames, durations, path):
    """שומר GIF עם רקע שקוף 1-bit. הטריק:
       1. Palette קבוע ומשותף לכל הפריימים, עם מגנטה באינדקס 0.
       2. Binary alpha threshold: פיקסלים עם alpha ≥ 128 → צבע הפיל; <128 →
          מגנטה (שקוף). זה מבטל פיקסלי-קצה 'בעלי גוון סגלגל' שגרמו לפיל
          להיראות סגול במקום שחור.
       3. transparency=0 + disposal=2 על כל הפריימים."""
    # פלטה משותפת: 0=מגנטה (שקוף), 1=שחור-פיל, 2=לבן, + ערכים נוספים אם יידרשו.
    # שאר הצבעים מתמלאים בדיתרינג של PIL.
    MASTER_PALETTE = [
        255, 0, 254,    # 0: מגנטה (שקוף ב-GIF)
        26, 26, 26,     # 1: pill fill
        255, 255, 255,  # 2: outline + bars + spinner
        128, 128, 128,  # 3: גוון ביניים (אם צריך)
    ] + [0] * (256 * 3 - 12)
    palette_template = Image.new("P", (1, 1))
    palette_template.putpalette(MASTER_PALETTE)

    palette_frames = []
    for f in frames:
        rgba = f.convert("RGBA")
        a = rgba.split()[3]
        # Binary threshold: alpha ≥ 128 = opaque (יישאר RGB), אחרת = מגנטה
        binary_mask = a.point(lambda x: 255 if x >= 128 else 0, mode="L")
        rgb = rgba.convert("RGB")
        # מתחילים ממסך מלא מגנטה
        composed = Image.new("RGB", rgba.size, (255, 0, 254))
        composed.paste(rgb, mask=binary_mask)
        # מקטטים לפלטה משותפת - מבטיח שמגנטה תמיד תהיה באינדקס 0
        p = composed.quantize(palette=palette_template, dither=Image.Dither.NONE)
        # מסמן ב-info של כל פריים שהשקיפות באינדקס 0 (חלק מהמציגים דורשים זאת)
        p.info["transparency"] = 0
        palette_frames.append(p)

    palette_frames[0].save(
        path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        loop=0,
        transparency=0,
        disposal=2,
        optimize=False,
    )
    print(f"  GIF: {path} ({len(frames)} frames, "
          f"{os.path.getsize(path)//1024} KB)")


def main():
    out_dir = os.path.dirname(__file__)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Rendering... canvas={CANVAS_W}x{CANVAS_H} "
          f"out={OUT_W}x{OUT_H} (supersample x{SUPERSAMPLE})")
    frames, durations = build_frames()
    print(f"Built {len(frames)} frames")

    save_apng(frames, durations, os.path.join(out_dir, "demo.png"))
    save_gif(frames, durations, os.path.join(out_dir, "demo.gif"))
    print("Done.")


if __name__ == "__main__":
    main()
