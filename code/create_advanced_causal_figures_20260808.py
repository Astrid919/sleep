"""Create publication-ready figures for the advanced causal sensitivity analyses."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "causal_reanalysis_20260808"
EXT = ROOT / "outputs" / "causal_extension_20260808"
FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def centered(draw, xy, text, text_font, fill):
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1]), text, font=text_font, fill=fill)


def line_with_markers(draw, points, color, width=5, radius=6):
    draw.line(points, fill=color, width=width, joint="curve")
    for x, y in points:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def core_forest_rows():
    category = read_tsv(BASE / "causal_models_sleep_categories.tsv")
    mi = read_tsv(BASE / "multiple_imputation_rubin_pooled.tsv")
    fg = read_tsv(BASE / "competing_risk_fine_gray.tsv")
    lag = read_tsv(EXT / "reverse_causation_lag_2y_5y.tsv")
    all_rows = category + mi + fg + lag
    index = {(row["model"], row["term"]): row for row in all_rows}
    specifications = [
        ("Main complete-case", "Model2_confounder", "Model3_health_status", "HR"),
        ("Free of prevalent CVD", "CVD_free_Model2_confounder", "CVD_free_Model3_health_status", "HR"),
        ("Exclude first 2 years", "lag2y_Model2_confounder", "lag2y_Model3_health_status", "HR"),
        ("Exclude first 5 years", "lag5y_Model2_confounder", "lag5y_Model3_health_status", "HR"),
        ("Multiple imputation", "MI_Model2_confounder", "MI_Model3_health_status", "HR"),
        ("Fine-Gray sensitivity", "FineGray_Model2_confounder", "FineGray_Model3_health_status", "SHR"),
    ]
    output = []
    for label, m2, m3, scale in specifications:
        for model_label, model in (("Confounder model", m2), ("Health-status model", m3)):
            row = index[(model, "sleep[>=9 h]")]
            output.append(
                {
                    "analysis": label,
                    "model_label": model_label,
                    "estimate": float(row["HR"]),
                    "lower": float(row["lower_95"]),
                    "upper": float(row["upper_95"]),
                    "scale": scale,
                }
            )
    return output


def draw_forest_panel(draw, rect, rows, labels, title, x_min=0.8, x_max=3.4, show_text=True):
    x1, y1, x2, y2 = rect
    draw.text((x1, y1), title, font=font(31, True), fill=(25, 35, 45))
    label_left = x1
    plot_left = x1 + 510
    plot_right = x2 - (285 if show_text else 35)
    top = y1 + 85
    bottom = y2 - 90

    def tx(value):
        return plot_left + (math.log(value) - math.log(x_min)) / (math.log(x_max) - math.log(x_min)) * (plot_right - plot_left)

    for value in (0.8, 1.0, 1.5, 2.0, 3.0):
        x = tx(value)
        draw.line((x, top, x, bottom), fill=(224, 228, 232), width=2)
        centered(draw, (x, bottom + 18), f"{value:g}", font(19), (60, 70, 80))
    draw.line((tx(1.0), top, tx(1.0), bottom), fill=(95, 100, 105), width=4)

    row_height = (bottom - top) / len(labels)
    colors = {"Confounder model": (36, 92, 142), "Health-status model": (207, 103, 34)}
    offsets = {"Confounder model": -12, "Health-status model": 12}
    by_key = {(r["analysis"], r["model_label"]): r for r in rows}
    for i, label in enumerate(labels):
        y_mid = top + (i + 0.5) * row_height
        if i % 2 == 0:
            draw.rectangle((x1, y_mid - row_height / 2, x2, y_mid + row_height / 2), fill=(248, 249, 250))
        draw.text((label_left + 8, y_mid - 15), label, font=font(21, True), fill=(40, 50, 60))
        for model_label in ("Confounder model", "Health-status model"):
            row = by_key[(label, model_label)]
            y = y_mid + offsets[model_label]
            color = colors[model_label]
            draw.line((tx(max(x_min, row["lower"])), y, tx(min(x_max, row["upper"])), y), fill=color, width=5)
            draw.line((tx(max(x_min, row["lower"])), y - 7, tx(max(x_min, row["lower"])), y + 7), fill=color, width=3)
            draw.line((tx(min(x_max, row["upper"])), y - 7, tx(min(x_max, row["upper"])), y + 7), fill=color, width=3)
            x = tx(row["estimate"])
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="white", width=2)
            if show_text:
                draw.text((plot_right + 18, y - 11), f"{row['estimate']:.2f} ({row['lower']:.2f}-{row['upper']:.2f})", font=font(17), fill=color)

    centered(draw, ((plot_left + plot_right) / 2, bottom + 52), "Hazard ratio (log scale)", font(21, True), (40, 50, 60))


def create_robustness_forest():
    image = Image.new("RGB", (1800, 1520), "white")
    draw = ImageDraw.Draw(image)
    draw.text((65, 38), "Robustness of the long-sleep association", font=font(40, True), fill=(20, 30, 40))
    rows = core_forest_rows()
    labels = ["Main complete-case", "Free of prevalent CVD", "Exclude first 2 years", "Exclude first 5 years", "Multiple imputation", "Fine-Gray sensitivity"]
    draw_forest_panel(draw, (70, 110, 1740, 805), rows, labels, "A. Core sensitivity analyses: >=9 versus 7-<8 h/night")

    loco_source = read_tsv(EXT / "leave_one_cycle_out_long_sleep.tsv")
    loco_rows = []
    for row in loco_source:
        label = f"Leave out {row['excluded_cycle']}"
        loco_rows.append(
            {
                "analysis": label,
                "model_label": "Confounder model" if row["adjustment_model"] == "Model2_confounder" else "Health-status model",
                "estimate": float(row["HR"]),
                "lower": float(row["lower_95"]),
                "upper": float(row["upper_95"]),
                "scale": "HR",
            }
        )
    loco_labels = [f"Leave out {cycle}" for cycle in sorted({row["excluded_cycle"] for row in loco_source})]
    draw_forest_panel(draw, (70, 840, 1740, 1420), loco_rows, loco_labels, "B. Leave-one-NHANES-cycle-out analyses")

    blue = (36, 92, 142)
    orange = (207, 103, 34)
    draw.line((1040, 69, 1095, 69), fill=blue, width=6)
    draw.ellipse((1061, 62, 1075, 76), fill=blue)
    draw.text((1110, 56), "Confounder model", font=font(20), fill=blue)
    draw.line((1375, 69, 1430, 69), fill=orange, width=6)
    draw.ellipse((1396, 62, 1410, 76), fill=orange)
    draw.text((1445, 56), "Health-status model", font=font(20), fill=orange)
    draw.text((70, 1460), "Fine-Gray rows show subdistribution hazard ratios; all other rows show cause-specific hazard ratios. Horizontal lines are 95% confidence intervals.", font=font(18), fill=(60, 70, 80))
    image.save(EXT / "Figure4_robustness_forest.png", dpi=(300, 300))


def create_standardized_cif():
    rows = read_tsv(EXT / "standardized_cumulative_incidence_curve.tsv")
    contrasts = read_tsv(EXT / "standardized_absolute_risk_contrasts.tsv")
    long10 = next(row for row in contrasts if row["sleep_group"] == ">=9 h" and float(row["horizon_years"]) == 10)
    bootstrap_replicates = int(float(long10.get("bootstrap_replicates", 100)))
    image = Image.new("RGB", (1800, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "Regression-standardized cumulative incidence of heart-disease death", font=font(39, True), fill=(20, 30, 40))
    left, right, top, bottom = 185, 1710, 145, 900
    y_max = 0.035

    def tx(year):
        return left + year / 10 * (right - left)

    def ty(risk):
        return bottom - risk / y_max * (bottom - top)

    for pct in (0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        y = ty(pct / 100)
        draw.line((left, y, right, y), fill=(226, 230, 234), width=2)
        label = f"{pct:.1f}%"
        box = draw.textbbox((0, 0), label, font=font(19))
        draw.text((left - 18 - (box[2] - box[0]), y - 10), label, font=font(19), fill=(60, 70, 80))
    for year in range(0, 11):
        x = tx(year)
        draw.line((x, bottom, x, bottom + 9), fill=(55, 65, 75), width=2)
        centered(draw, (x, bottom + 20), str(year), font(19), (60, 70, 80))
    draw.line((left, top, left, bottom), fill=(55, 65, 75), width=3)
    draw.line((left, bottom, right, bottom), fill=(55, 65, 75), width=3)

    colors = {
        "<6 h": (129, 94, 167),
        "6-<7 h": (77, 153, 102),
        "7-<8 h": (36, 92, 142),
        "8-<9 h": (112, 112, 112),
        ">=9 h": (207, 103, 34),
    }
    grouped = {level: [r for r in rows if r["sleep_group"] == level] for level in colors}
    for level in ("7-<8 h", ">=9 h"):
        group = grouped[level]
        lower = [(tx(float(r["years"])), ty(float(r["lower_95_bootstrap"]))) for r in group]
        upper = [(tx(float(r["years"])), ty(float(r["upper_95_bootstrap"]))) for r in reversed(group)]
        fill = (223, 232, 241) if level == "7-<8 h" else (248, 229, 215)
        draw.polygon(lower + upper, fill=fill)
    for level, color in colors.items():
        points = [(tx(float(r["years"])), ty(float(r["risk"]))) for r in grouped[level]]
        line_with_markers(draw, points, color, width=6 if level in ("7-<8 h", ">=9 h") else 4, radius=0)

    centered(draw, ((left + right) / 2, bottom + 62), "Years since baseline examination", font(23, True), (40, 50, 60))
    y_label = Image.new("RGBA", (650, 60), (255, 255, 255, 0))
    y_draw = ImageDraw.Draw(y_label)
    y_draw.text((0, 8), "Standardized cumulative incidence", font=font(23, True), fill=(40, 50, 60))
    rotated = y_label.rotate(90, expand=True)
    image.paste(rotated, (25, int((top + bottom - rotated.height) / 2)), rotated)

    legend_x, legend_y = 230, 950
    for i, (level, color) in enumerate(colors.items()):
        x = legend_x + i * 285
        draw.line((x, legend_y, x + 55, legend_y), fill=color, width=7)
        draw.text((x + 68, legend_y - 13), level, font=font(20), fill=color)
    rd = 100 * float(long10["risk_difference"])
    lo = 100 * float(long10["rd_lower_95_bootstrap"])
    hi = 100 * float(long10["rd_upper_95_bootstrap"])
    draw.rounded_rectangle((985, 190, 1665, 310), radius=18, fill=(255, 250, 245), outline=(207, 103, 34), width=3)
    draw.text((1015, 210), "10-year >=9 versus 7-<8 h", font=font(22, True), fill=(140, 68, 28))
    draw.text((1015, 252), f"Risk difference: {rd:.2f} percentage points ({lo:.2f} to {hi:.2f})", font=font(20), fill=(70, 55, 45))
    draw.text((70, 1035), f"Model 2 regression standardization used two survey-weighted cause-specific Cox models. Shading shows 95% PSU-bootstrap intervals for the reference and long-sleep groups ({bootstrap_replicates} replicates).", font=font(18), fill=(60, 70, 80))
    image.save(EXT / "Figure5_standardized_cumulative_incidence.png", dpi=(300, 300))


def create_sequential_attenuation():
    rows = read_tsv(EXT / "health_status_sequential_attenuation.tsv")
    image = Image.new("RGB", (2000, 980), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "Sequential health-status adjustment for long sleep", font=font(40, True), fill=(20, 30, 40))
    left, right, top, bottom = 660, 1465, 150, 775
    x_min, x_max = 0.8, 2.6

    def tx(value):
        return left + (math.log(value) - math.log(x_min)) / (math.log(x_max) - math.log(x_min)) * (right - left)

    for value in (0.8, 1.0, 1.25, 1.5, 2.0, 2.5):
        x = tx(value)
        draw.line((x, top, x, bottom), fill=(224, 228, 232), width=2)
        centered(draw, (x, bottom + 20), f"{value:g}", font(20), (60, 70, 80))
    draw.line((tx(1.0), top, tx(1.0), bottom), fill=(95, 100, 105), width=4)
    step = (bottom - top) / len(rows)
    for i, row in enumerate(rows):
        y = top + (i + 0.5) * step
        if i % 2 == 0:
            draw.rectangle((65, y - step / 2, 1935, y + step / 2), fill=(248, 249, 250))
        label = row["description"]
        draw.text((85, y - 14), label, font=font(22, True if i in (1, 5) else False), fill=(40, 50, 60))
        lo, hr, hi = float(row["lower_95"]), float(row["HR"]), float(row["upper_95"])
        color = (36, 92, 142) if i <= 1 else (207, 103, 34)
        draw.line((tx(lo), y, tx(hi), y), fill=color, width=6)
        draw.line((tx(lo), y - 8, tx(lo), y + 8), fill=color, width=3)
        draw.line((tx(hi), y - 8, tx(hi), y + 8), fill=color, width=3)
        x = tx(hr)
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color, outline="white", width=2)
        draw.text((right + 30, y - 13), f"{hr:.2f} ({lo:.2f}-{hi:.2f})", font=font(20), fill=color)
        attenuation = row["attenuation_vs_confounder_percent"]
        text = "reference" if i == 1 else ("-" if attenuation == "nan" else f"{float(attenuation):.1f}%")
        draw.text((1825, y - 13), text, font=font(20), fill=(70, 80, 90))

    draw.text((1760, 108), "Attenuation*", font=font(19, True), fill=(60, 70, 80))
    centered(draw, ((left + right) / 2, bottom + 64), "Hazard ratio for >=9 versus 7-<8 h/night (log scale)", font(22, True), (40, 50, 60))
    draw.text((70, 875), "*Percent reduction in the log-HR relative to the confounder model. All stages use the same SIRI-complete sample (n=31,367; 830 heart-disease deaths).", font=font(19), fill=(60, 70, 80))
    draw.text((70, 915), "Sequential attenuation is descriptive and may reflect confounding, pathway blocking, non-collapsibility, or combinations thereof; it is not a mediated proportion.", font=font(19), fill=(60, 70, 80))
    image.save(EXT / "Figure6_sequential_health_status_attenuation.png", dpi=(300, 300))


def main():
    EXT.mkdir(parents=True, exist_ok=True)
    create_robustness_forest()
    create_standardized_cif()
    create_sequential_attenuation()
    print(EXT)


if __name__ == "__main__":
    main()
