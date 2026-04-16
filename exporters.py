import csv
import io
from datetime import UTC, datetime
from typing import Any

from fpdf import FPDF


def make_safe_filename(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in raw.strip())
    compact = "_".join(part for part in cleaned.split("_") if part)
    return compact or "forecast_export"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    return value


def build_forecast_csv_bytes(
    product_name: str,
    historical: list[dict[str, Any]],
    forecast: list[dict[str, Any]],
    summary: dict[str, Any],
    created_at: str | None,
) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Product Name", product_name])
    writer.writerow(["Generated At", _format_timestamp(created_at)])
    writer.writerow([])

    writer.writerow(["Summary"])
    writer.writerow(["High Demand Threshold", summary["high_demand_threshold"]])
    writer.writerow(["Next Month Forecast", summary["next_month"]["forecast"]])
    writer.writerow(["Next Month High Demand", summary["next_month"]["is_high_demand"]])
    writer.writerow(["Next 5 Months Avg Forecast", summary["next_5_months"]["average_forecast"]])
    writer.writerow(["Next 5 Months High-Demand Months", summary["next_5_months"]["months_high_demand"]])
    writer.writerow(["Next 5 Months High Demand", summary["next_5_months"]["is_high_demand"]])
    writer.writerow(["Next 5 Years Growth Percent", summary["next_5_years"]["growth_percent"]])
    writer.writerow(["Next 5 Years High Demand", summary["next_5_years"]["is_high_demand"]])
    writer.writerow([])

    writer.writerow(["Historical Data"])
    writer.writerow(["date", "demand"])
    for row in historical:
        writer.writerow([row["date"], row["demand"]])

    writer.writerow([])
    writer.writerow(["Forecast Data"])
    writer.writerow(["date", "demand"])
    for row in forecast:
        writer.writerow([row["date"], row["demand"]])

    return output.getvalue().encode("utf-8")


def build_forecast_pdf_bytes(
    product_name: str,
    historical: list[dict[str, Any]],
    forecast: list[dict[str, Any]],
    summary: dict[str, Any],
    created_at: str | None,
) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)

    lines = [
        "Demand Forecast Report",
        f"Product: {product_name}",
        f"Generated At: {_format_timestamp(created_at)}",
        "",
        f"High-Demand Threshold: {summary['high_demand_threshold']}",
        f"Next Month Forecast: {summary['next_month']['forecast']}",
        f"Next Month High Demand: {summary['next_month']['is_high_demand']}",
        f"Next 5 Months Avg: {summary['next_5_months']['average_forecast']}",
        f"Next 5 Months High-Demand Months: {summary['next_5_months']['months_high_demand']}",
        f"Next 5 Months High Demand: {summary['next_5_months']['is_high_demand']}",
        f"Next 5 Years Growth %: {summary['next_5_years']['growth_percent']}",
        f"Next 5 Years High Demand: {summary['next_5_years']['is_high_demand']}",
        "",
        "Historical Data Overview:",
    ]

    for row in historical:
        lines.append(f"- {row['date']} : {row['demand']}")

    lines.append("")
    lines.append("Upcoming Forecast:")
    for row in forecast:
        lines.append(f"- {row['date']} : {row['demand']}")

    lines.append("")
    lines.append(f"Exported at {datetime.now(UTC).isoformat()}")

    for text_line in lines:
        safe_line = text_line.encode("latin-1", "replace").decode("latin-1")
        pdf.cell(w=0, h=5, text=safe_line, new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
