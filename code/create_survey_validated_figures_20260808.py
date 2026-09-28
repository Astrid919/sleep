"""Create publication figures for the survey-validated reanalysis."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import create_advanced_causal_figures_20260808 as legacy_figures


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "survey_validated_reanalysis_20260808"
EXT = ROOT / "outputs" / "survey_validated_extension_20260808"
FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def centered(draw, x, y, text, text_font, fill=(45, 52, 58)):
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text((x - (box[2] - box[0]) / 2, y), text, font=text_font, fill=fill)


def color_scale(value: float, lower: float = 0.8, upper: float = 1.8):
    anchors = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]
    position = min(1.0, max(0.0, (value - lower) / (upper - lower))) * (len(anchors) - 1)
    left = int(math.floor(position))
    right = min(left + 1, len(anchors) - 1)
    fraction = position - left
    return tuple(int(round(anchors[left][i] * (1 - fraction) + anchors[right][i] * fraction)) for i in range(3))


def bias_contour() -> None:
    rows = read_tsv(EXT / "quantitative_bias_contour_grid.tsv")
    image = Image.new("RGB", (2500, 950), "white")
    draw = ImageDraw.Draw(image)
    draw.text((75, 35), "Quantitative bias contours for the long-sleep association", font=font(42, True), fill=(28, 36, 43))
    baselines = (0.10, 0.20, 0.30)
    for panel, baseline in enumerate(baselines):
        use = [row for row in rows if abs(float(row["p_unmeasured_confounder_reference"]) - baseline) < 1e-9]
        x_values = sorted({float(row["prevalence_difference_long_minus_reference"]) for row in use})
        y_values = sorted({float(row["RR_unmeasured_confounder_outcome"]) for row in use})
        values = {(float(row["prevalence_difference_long_minus_reference"]), float(row["RR_unmeasured_confounder_outcome"])): float(row["bias_adjusted_HR_approx"]) for row in use}
        left = 100 + panel * 765
        right = left + 630
        top, bottom = 165, 730

        def tx(value):
            return left + value / max(x_values) * (right - left)

        def ty(value):
            return bottom - (value - 1.0) / 5.0 * (bottom - top)

        dx = (right - left) / max(1, len(x_values) - 1)
        dy = (bottom - top) / max(1, len(y_values) - 1)
        for x in x_values:
            for y in y_values:
                estimate = values.get((x, y))
                if estimate is None:
                    continue
                px, py = tx(x), ty(y)
                draw.rectangle((px - dx / 2, py - dy / 2, px + dx / 2 + 1, py + dy / 2 + 1), fill=color_scale(estimate))

        null_points = []
        for x in x_values:
            series = [(y, values[(x, y)]) for y in y_values if (x, y) in values]
            crossing = None
            for (y0, v0), (y1, v1) in zip(series, series[1:]):
                if (v0 - 1) * (v1 - 1) <= 0 and v0 != v1:
                    crossing = y0 + (1 - v0) * (y1 - y0) / (v1 - v0)
                    break
            if crossing is not None:
                null_points.append((tx(x), ty(crossing)))
        if len(null_points) > 1:
            draw.line(null_points, fill=(190, 42, 42), width=7)
            label_x, label_y = null_points[len(null_points) // 2]
            draw.rounded_rectangle((label_x - 80, label_y - 42, label_x + 92, label_y - 8), radius=8, fill=(255, 245, 245))
            draw.text((label_x - 70, label_y - 39), "Adjusted HR = 1", font=font(18, True), fill=(170, 35, 35))
        draw.rectangle((left, top, right, bottom), outline=(55, 62, 68), width=3)
        for x_tick in (0.0, 0.2, 0.4, 0.6):
            if x_tick <= max(x_values) + 1e-9:
                x_pixel = tx(x_tick)
                draw.line((x_pixel, bottom, x_pixel, bottom + 9), fill=(55, 62, 68), width=2)
                centered(draw, x_pixel, bottom + 15, f"{x_tick:.1f}", font(19))
        for y_tick in (1, 2, 3, 4, 5, 6):
            y_pixel = ty(y_tick)
            draw.line((left - 8, y_pixel, left, y_pixel), fill=(55, 62, 68), width=2)
            if panel == 0:
                box = draw.textbbox((0, 0), str(y_tick), font=font(19))
                draw.text((left - 18 - (box[2] - box[0]), y_pixel - 10), str(y_tick), font=font(19), fill=(45, 52, 58))
        centered(draw, (left + right) / 2, 110, f"Reference prevalence = {baseline:.0%}", font(27, True))
        centered(draw, (left + right) / 2, 785, "Prevalence difference", font(23, True))
        centered(draw, (left + right) / 2, 815, "(long sleep − reference)", font(21))
    y_label = Image.new("RGBA", (600, 65), (255, 255, 255, 0))
    y_draw = ImageDraw.Draw(y_label)
    y_draw.text((0, 8), "Confounder–mortality risk ratio", font=font(24, True), fill=(45, 52, 58))
    rotated = y_label.rotate(90, expand=True)
    image.paste(rotated, (15, 215), rotated)
    bar_left, bar_right, bar_top, bar_bottom = 2390, 2440, 185, 690
    for pixel in range(bar_top, bar_bottom):
        value = 1.8 - (pixel - bar_top) / (bar_bottom - bar_top) * 1.0
        draw.line((bar_left, pixel, bar_right, pixel), fill=color_scale(value), width=1)
    draw.rectangle((bar_left, bar_top, bar_right, bar_bottom), outline=(55, 62, 68), width=2)
    for value in (0.8, 1.0, 1.2, 1.4, 1.6, 1.8):
        pixel = bar_bottom - (value - 0.8) * (bar_bottom - bar_top)
        draw.text((bar_right + 10, pixel - 10), f"{value:.1f}", font=font(18), fill=(45, 52, 58))
    draw.text((2315, 720), "Bias-adjusted HR", font=font(20, True), fill=(45, 52, 58))
    draw.text((90, 895), "The red contour marks parameter combinations that move the Model 2 point estimate to the null; this does not identify the prevalence or effect of any specific unmeasured factor.", font=font(19), fill=(65, 72, 78))
    image.save(EXT / "FigureS_bias_contour.png", dpi=(300, 300))


def draw_domain_panel(draw, rectangle, rows, key, labels, title):
    left, top, right, bottom = rectangle
    plot_left, plot_right = left + 350, right - 150
    draw.text((left, top), title, font=font(27, True), fill=(35, 43, 50))

    def tx(value):
        return plot_left + (math.log(value) - math.log(0.95)) / (math.log(2.5) - math.log(0.95)) * (plot_right - plot_left)

    use = [next(row for row in rows if row[key] == value) for value in labels]
    chart_top, chart_bottom = top + 70, bottom - 70
    row_height = (chart_bottom - chart_top) / len(use)
    for tick in (1.0, 1.25, 1.5, 2.0, 2.5):
        x = tx(tick)
        draw.line((x, chart_top, x, chart_bottom), fill=(225, 228, 231), width=2)
        centered(draw, x, chart_bottom + 12, f"{tick:g}", font(18))
    draw.line((tx(1.0), chart_top, tx(1.0), chart_bottom), fill=(95, 100, 105), width=4)
    for index, row in enumerate(use):
        y = chart_top + (index + 0.5) * row_height
        draw.text((left + 10, y - 12), labels[row[key]], font=font(20, index == 0), fill=(45, 52, 58))
        estimate, lower, upper = float(row["HR"]), float(row["lower_95"]), float(row["upper_95"])
        draw.line((tx(lower), y, tx(upper), y), fill=(47, 111, 159), width=6)
        draw.line((tx(lower), y - 7, tx(lower), y + 7), fill=(47, 111, 159), width=3)
        draw.line((tx(upper), y - 7, tx(upper), y + 7), fill=(47, 111, 159), width=3)
        x = tx(estimate)
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=(47, 111, 159))
        attenuation = float(row.get("attenuation_vs_Model2_percent", row.get("attenuation_vs_confounder_percent", "nan")))
        text = "reference" if abs(attenuation) < 1e-9 else f"{attenuation:.1f}%"
        draw.text((plot_right + 20, y - 11), text, font=font(18), fill=(70, 78, 85))
    centered(draw, (plot_left + plot_right) / 2, chart_bottom + 47, "Hazard ratio (log scale)", font(20, True))


def domain_attenuation() -> None:
    one = read_tsv(EXT / "health_status_domain_one_at_a_time.tsv")
    cumulative = read_tsv(EXT / "health_status_sequential_attenuation.tsv")
    one_labels = {
        "Model2_only": "Model 2",
        "Model2_plus_BMI": "+ BMI only",
        "Model2_plus_HTN_DM": "+ HTN/diabetes only",
        "Model2_plus_CVD": "+ prevalent CVD only",
        "Model2_plus_SIRI": "+ log-SIRI only",
    }
    cumulative_labels = {
        "B_confounder": "Model 2",
        "C_plus_BMI": "+ BMI",
        "D_plus_HTN_DM": "+ HTN/diabetes",
        "E_plus_CVD": "+ prevalent CVD",
        "F_plus_SIRI": "+ log-SIRI",
    }
    image = Image.new("RGB", (2300, 980), "white")
    draw = ImageDraw.Draw(image)
    draw.text((65, 30), "Health-status domains and the long-sleep coefficient", font=font(40, True), fill=(25, 34, 42))
    draw.text((1940, 112), "Log-HR attenuation", font=font(19, True), fill=(65, 72, 78))
    draw_domain_panel(draw, (65, 110, 1130, 865), one, "model", one_labels, "A. One domain added to Model 2")
    draw_domain_panel(draw, (1190, 110, 2260, 865), [row for row in cumulative if row["stage"] in cumulative_labels], "stage", cumulative_labels, "B. Cumulative sequence")
    draw.text((65, 915), "All estimates use the same SIRI-complete sample (n=31,367; 830 deaths). Attenuation is descriptive, order-dependent, non-additive, and not a mediated proportion.", font=font(19), fill=(65, 72, 78))
    image.save(EXT / "Figure3_health_status_domain_attenuation.png", dpi=(300, 300))


def ph_time_specific() -> None:
    rows = [row for row in read_tsv(EXT / "proportional_hazards_time_specific_HR.tsv") if row["term"] == "sleep[>=9 h]"]
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((65, 35), "Time-specific long-sleep hazard ratios", font=font(40, True), fill=(25, 34, 42))
    left, right, top, bottom = 190, 1510, 150, 720

    def tx(year):
        return left + (year - 1) / 9 * (right - left)

    def ty(value):
        return bottom - (math.log(value) - math.log(0.4)) / (math.log(5.5) - math.log(0.4)) * (bottom - top)

    for value in (0.5, 1.0, 2.0, 4.0):
        y = ty(value)
        draw.line((left, y, right, y), fill=(225, 228, 231), width=2)
        draw.text((95, y - 11), f"{value:g}", font=font(19), fill=(55, 62, 68))
    draw.line((left, ty(1.0), right, ty(1.0)), fill=(95, 100, 105), width=4)
    for year in (1, 5, 10):
        x = tx(year)
        draw.line((x, bottom, x, bottom + 9), fill=(55, 62, 68), width=2)
        centered(draw, x, bottom + 17, str(year), font(19))
    colors = {"Model2_confounder": (47, 111, 159), "Model3_health_status": (192, 90, 50)}
    names = {"Model2_confounder": "Model 2", "Model3_health_status": "Model 3"}
    offsets = {"Model2_confounder": -13, "Model3_health_status": 13}
    for model in names:
        use = sorted([row for row in rows if row["model"] == model], key=lambda row: float(row["follow_up_years"]))
        points = []
        for row in use:
            x = tx(float(row["follow_up_years"])) + offsets[model]
            estimate, lower, upper = float(row["HR"]), float(row["lower_95"]), float(row["upper_95"])
            points.append((x, ty(estimate)))
            draw.line((x, ty(lower), x, ty(upper)), fill=colors[model], width=5)
            draw.line((x - 8, ty(lower), x + 8, ty(lower)), fill=colors[model], width=3)
            draw.line((x - 8, ty(upper), x + 8, ty(upper)), fill=colors[model], width=3)
            draw.ellipse((x - 8, ty(estimate) - 8, x + 8, ty(estimate) + 8), fill=colors[model])
        draw.line(points, fill=colors[model], width=5)
    draw.line((1050, 85, 1105, 85), fill=colors["Model2_confounder"], width=6)
    draw.text((1115, 71), "Model 2", font=font(20), fill=colors["Model2_confounder"])
    draw.line((1260, 85, 1315, 85), fill=colors["Model3_health_status"], width=6)
    draw.text((1325, 71), "Model 3", font=font(20), fill=colors["Model3_health_status"])
    centered(draw, (left + right) / 2, bottom + 58, "Follow-up time (years)", font(22, True))
    draw.text((65, 820), "Sleep × log(time) interaction: P=0.312 for ≥9 h in Model 2 and P=0.321 in Model 3; global interaction P=0.817 and 0.759, respectively.", font=font(19), fill=(65, 72, 78))
    image.save(EXT / "FigureS_PH_time_specific_HR.png", dpi=(300, 300))


def legacy_updated_figures() -> None:
    legacy_figures.BASE = BASE
    legacy_figures.EXT = EXT
    legacy_figures.create_robustness_forest()
    legacy_figures.create_standardized_cif()


def main() -> None:
    bias_contour()
    domain_attenuation()
    ph_time_specific()
    legacy_updated_figures()
    print(EXT)


if __name__ == "__main__":
    main()
