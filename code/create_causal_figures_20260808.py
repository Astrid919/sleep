"""Create publication-ready causal and spline figures with Pillow."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "causal_reanalysis_20260808"
FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color, width=4, dashed=False):
    x1, y1 = start
    x2, y2 = end
    if dashed:
        segments = 12
        for i in range(0, segments, 2):
            a = i / segments
            b = min(1.0, (i + 1) / segments)
            draw.line((x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), fill=color, width=width)
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 18
    spread = 0.55
    points = [
        (x2, y2),
        (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread)),
        (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread)),
    ]
    draw.polygon(points, fill=color)


def rounded_box(draw, xy, text, fill, outline, text_color=(25, 35, 45), size=28, subtitle=None):
    draw.rounded_rectangle(xy, radius=20, fill=fill, outline=outline, width=3)
    x1, y1, x2, y2 = xy
    lines = text.split("\n")
    total = len(lines) * (size + 3) + (20 if subtitle else 0)
    y = (y1 + y2 - total) / 2
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font(size, True))
        draw.text(((x1 + x2 - (box[2] - box[0])) / 2, y), line, font=font(size, True), fill=text_color)
        y += size + 3
    if subtitle:
        box = draw.textbbox((0, 0), subtitle, font=font(19))
        draw.text(((x1 + x2 - (box[2] - box[0])) / 2, y + 4), subtitle, font=font(19), fill=(70, 80, 90))


def create_dag():
    image = Image.new("RGB", (1800, 1180), "white")
    draw = ImageDraw.Draw(image)
    blue = (42, 92, 137)
    teal = (37, 122, 122)
    orange = (198, 103, 42)
    gray = (95, 105, 115)
    draw.text((70, 36), "Causal structures guiding model interpretation", font=font(40, True), fill=(20, 30, 40))

    draw.rounded_rectangle((45, 105, 875, 1000), radius=24, outline=(180, 190, 200), width=3)
    draw.text((80, 132), "A. Etiologic pathway of interest", font=font(31, True), fill=blue)
    rounded_box(draw, (80, 220, 365, 360), "Baseline\nconfounders", (232, 241, 250), blue, size=27, subtitle="C")
    rounded_box(draw, (455, 220, 740, 360), "Sleep\nduration", (226, 244, 241), teal, size=28, subtitle="A")
    rounded_box(draw, (455, 470, 740, 610), "Inflammatory\nstatus", (250, 242, 224), orange, size=27, subtitle="M: SIRI / SII")
    rounded_box(draw, (455, 720, 740, 875), "Cardiometabolic\nhealth", (244, 235, 245), (126, 80, 130), size=26, subtitle="H: BMI, HTN, diabetes, CVD")
    rounded_box(draw, (80, 720, 365, 875), "Heart-disease\nmortality", (242, 238, 238), gray, size=27, subtitle="Y")
    arrow(draw, (365, 290), (455, 290), blue)
    arrow(draw, (220, 360), (220, 720), blue)
    arrow(draw, (365, 330), (455, 500), blue)
    arrow(draw, (365, 350), (455, 755), blue)
    arrow(draw, (598, 360), (598, 470), teal, dashed=True)
    arrow(draw, (598, 610), (598, 720), orange, dashed=True)
    arrow(draw, (455, 795), (365, 795), (126, 80, 130))
    arrow(draw, (455, 305), (325, 720), teal)
    draw.multiline_text(
        (91, 902),
        "Model 2 adjusts C. Model 3 additionally adjusts H\nand may block part of the hypothesized pathway.",
        font=font(19), fill=(55, 65, 75), spacing=7,
    )

    draw.rounded_rectangle((925, 105, 1755, 1000), radius=24, outline=(180, 190, 200), width=3)
    draw.text((960, 132), "B. Reverse-causation alternative", font=font(31, True), fill=orange)
    rounded_box(draw, (970, 220, 1255, 360), "Baseline\nconfounders", (232, 241, 250), blue, size=27, subtitle="C")
    rounded_box(draw, (1370, 220, 1660, 360), "Sleep\nduration", (226, 244, 241), teal, size=28, subtitle="A")
    rounded_box(draw, (1135, 470, 1495, 625), "Underlying poor health /\nprevalent disease", (251, 232, 224), orange, size=25, subtitle="U / H")
    rounded_box(draw, (1370, 735, 1660, 875), "Inflammatory\nmarkers", (250, 242, 224), orange, size=27, subtitle="M")
    rounded_box(draw, (970, 735, 1255, 875), "Heart-disease\nmortality", (242, 238, 238), gray, size=27, subtitle="Y")
    arrow(draw, (1255, 290), (1370, 290), blue)
    arrow(draw, (1110, 360), (1110, 735), blue)
    arrow(draw, (1315, 470), (1480, 360), orange)
    arrow(draw, (1250, 625), (1135, 735), orange)
    arrow(draw, (1410, 625), (1510, 735), orange)
    arrow(draw, (1370, 805), (1255, 805), orange, dashed=True)
    draw.multiline_text(
        (966, 902),
        "CVD-free and lag analyses reduce—but cannot eliminate—\nthis alternative explanation.",
        font=font(19), fill=(55, 65, 75), spacing=7,
    )

    draw.line((85, 1052, 250, 1052), fill=teal, width=5)
    draw.text((270, 1038), "assumed causal path", font=font(20), fill=(50, 60, 70))
    for x in range(610, 775, 25):
        draw.line((x, 1052, x + 13, 1052), fill=orange, width=5)
    draw.text((795, 1038), "temporally uncertain pathway", font=font(20), fill=(50, 60, 70))
    draw.text((85, 1100), "SIRI and SII were measured at the same baseline visit as sleep duration; pathway analyses are exploratory, not causal mediation estimates.", font=font(21), fill=(50, 60, 70))
    image.save(OUT / "Figure1_causal_dag.png", dpi=(300, 300))


def read_tsv(name):
    with (OUT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def draw_panel(draw, rect, rows, title, ylabel, line_color, ylimits, p_text):
    x1, y1, x2, y2 = rect
    left, right, top, bottom = x1 + 115, x2 - 35, y1 + 95, y2 - 105
    draw.text((x1 + 25, y1 + 20), title, font=font(29, True), fill=(25, 35, 45))
    x_min, x_max = 3.0, 11.0
    y_min, y_max = ylimits

    def tx(value):
        return left + (value - x_min) / (x_max - x_min) * (right - left)

    def ty(value):
        clipped = min(y_max, max(y_min, value))
        return bottom - (clipped - y_min) / (y_max - y_min) * (bottom - top)

    for value in np_ticks(y_min, y_max, 5):
        y = ty(value)
        draw.line((left, y, right, y), fill=(224, 228, 232), width=2)
        label = f"{value:.1f}"
        box = draw.textbbox((0, 0), label, font=font(20))
        draw.text((left - 15 - (box[2] - box[0]), y - 11), label, font=font(20), fill=(60, 70, 80))
    for value in range(3, 12):
        x = tx(value)
        draw.line((x, bottom, x, bottom + 8), fill=(60, 70, 80), width=2)
        draw.text((x - 7, bottom + 16), str(value), font=font(20), fill=(60, 70, 80))
    draw.line((left, top, left, bottom), fill=(55, 65, 75), width=3)
    draw.line((left, bottom, right, bottom), fill=(55, 65, 75), width=3)
    draw.line((left, ty(1.0), right, ty(1.0)), fill=(100, 105, 110), width=3)
    points_lower = [(tx(float(r["sleep_hours"])), ty(float(r["lower_95"]))) for r in rows]
    points_upper = [(tx(float(r["sleep_hours"])), ty(float(r["upper_95"]))) for r in reversed(rows)]
    draw.polygon(points_lower + points_upper, fill=(*line_color, 45) if image_mode_supports_alpha(draw) else (220, 230, 238))
    points = [(tx(float(r["sleep_hours"])), ty(float(r.get("HR", r.get("geometric_mean_ratio"))))) for r in rows]
    draw.line(points, fill=line_color, width=6, joint="curve")
    draw.text((left + 15, top + 15), p_text, font=font(20), fill=(40, 50, 60))
    x_label = "Sleep duration (h/night)"
    box = draw.textbbox((0, 0), x_label, font=font(22, True))
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 55), x_label, font=font(22, True), fill=(40, 50, 60))
    # Rotated y-axis label.
    label_img = Image.new("RGBA", (350, 50), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label_img)
    label_draw.text((0, 5), ylabel, font=font(22, True), fill=(40, 50, 60))
    rotated = label_img.rotate(90, expand=True)
    draw._image.paste(rotated, (x1 + 12, int((top + bottom - rotated.height) / 2)), rotated)


def image_mode_supports_alpha(draw):
    return False


def np_ticks(y_min, y_max, count):
    if count <= 1:
        return [y_min]
    return [y_min + i * (y_max - y_min) / (count - 1) for i in range(count)]


def create_mortality_rcs():
    all_rows = read_tsv("causal_models_sleep_rcs_curve.tsv")
    summaries = {row["model"]: row for row in read_tsv("causal_models_sleep_rcs_summary.tsv")}
    models = [
        ("full_Model2_confounder_RCS", "A. Full analytic cohort"),
        ("CVD_free_Model2_confounder_RCS", "B. Free of prevalent CVD at baseline"),
    ]
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    draw._image = image
    for index, (model, title) in enumerate(models):
        rows = [row for row in all_rows if row["model"] == model]
        summary = summaries[model]
        text = f"P-overall={float(summary['overall_p']):.3f}; P-nonlinear={float(summary['nonlinear_p']):.3f}"
        draw_panel(draw, (40 + index * 880, 30, 880 + index * 880, 860), rows, title, "Hazard ratio (95% CI)", (35, 93, 139), (0.4, 3.0), text)
    image.save(OUT / "Figure2_sleep_mortality_rcs.png", dpi=(300, 300))


def create_inflammation_rcs():
    all_rows = read_tsv("inflammation_sleep_rcs_curve.tsv")
    summaries = {row["mediator"]: row for row in read_tsv("inflammation_sleep_rcs_summary.tsv")}
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    draw._image = image
    for index, mediator in enumerate(("SIRI", "SII")):
        rows = [row for row in all_rows if row["mediator"] == mediator]
        summary = summaries[mediator]
        text = f"P-overall={float(summary['overall_p']):.3f}; P-nonlinear={float(summary['nonlinear_p']):.3f}"
        draw_panel(draw, (40 + index * 880, 30, 880 + index * 880, 860), rows, f"{'A' if index == 0 else 'B'}. {mediator}", "Geometric mean ratio (95% CI)", (185, 91, 36), (0.85, 1.18), text)
    image.save(OUT / "Figure3_inflammation_pathway_rcs.png", dpi=(300, 300))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    create_dag()
    create_mortality_rcs()
    create_inflammation_rcs()
    print(OUT)


if __name__ == "__main__":
    main()
