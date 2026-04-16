import csv
import io
import math
from datetime import date, datetime
from statistics import mean, stdev
from typing import Any


class ForecastInputError(ValueError):
    pass


def _add_months(value: date, months: int) -> date:
    total_month = (value.month - 1) + months
    year = value.year + (total_month // 12)
    month = (total_month % 12) + 1
    return date(year, month, 1)


def _parse_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None

    direct = value.replace("/", "-")
    try:
        parsed = datetime.fromisoformat(direct)
        return date(parsed.year, parsed.month, 1)
    except ValueError:
        pass

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    return None


def _parse_number(raw: str) -> float | None:
    value = raw.strip().replace(",", "")
    if not value:
        return None
    try:
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except ValueError:
        return None


def _normalize_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for original in columns:
        mapping[original.strip().lower()] = original
    return mapping


def parse_history_csv(raw_bytes: bytes) -> list[dict[str, Any]]:
    try:
        decoded = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ForecastInputError("CSV must use UTF-8 encoding.") from exc

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ForecastInputError("CSV header is missing.")

    normalized = _normalize_columns(reader.fieldnames)
    date_candidates = ["date", "month", "timestamp", "ds"]
    demand_candidates = ["demand", "sales", "quantity", "y", "value"]

    date_column = next((normalized[c] for c in date_candidates if c in normalized), None)
    demand_column = next((normalized[c] for c in demand_candidates if c in normalized), None)
    if not date_column or not demand_column:
        raise ForecastInputError(
            "CSV needs date column (date/month/timestamp) and demand column (demand/sales/quantity)."
        )

    monthly_totals: dict[date, float] = {}
    for row in reader:
        raw_date = row.get(date_column, "")
        raw_demand = row.get(demand_column, "")
        parsed_date = _parse_date(raw_date)
        parsed_demand = _parse_number(raw_demand)
        if parsed_date is None or parsed_demand is None:
            continue
        monthly_totals[parsed_date] = monthly_totals.get(parsed_date, 0.0) + parsed_demand

    if not monthly_totals:
        raise ForecastInputError("No valid date/demand rows found in CSV.")

    first_month = min(monthly_totals.keys())
    last_month = max(monthly_totals.keys())
    monthly_points: list[dict[str, Any]] = []

    cursor = first_month
    while cursor <= last_month:
        monthly_points.append(
            {
                "date": cursor,
                "demand": float(monthly_totals.get(cursor, 0.0)),
            }
        )
        cursor = _add_months(cursor, 1)

    if len(monthly_points) < 4:
        raise ForecastInputError("Please provide at least 4 months of historical data.")

    return monthly_points


def _linear_trend(values: list[float]) -> tuple[float, float]:
    count = len(values)
    if count == 1:
        return 0.0, values[0]

    x_mean = (count - 1) / 2
    y_mean = mean(values)
    numerator = 0.0
    denominator = 0.0
    for i, y in enumerate(values):
        dx = i - x_mean
        numerator += dx * (y - y_mean)
        denominator += dx * dx

    slope = 0.0 if denominator == 0 else numerator / denominator
    intercept = y_mean - (slope * x_mean)
    return slope, intercept


def _seasonal_adjustments(dates: list[date], values: list[float], slope: float, intercept: float) -> dict[int, float]:
    adjustments: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    if len(values) < 24:
        return {month: 0.0 for month in range(1, 13)}

    for i, point_date in enumerate(dates):
        trend_value = intercept + (slope * i)
        adjustments[point_date.month].append(values[i] - trend_value)

    month_adjustments: dict[int, float] = {}
    for month, vals in adjustments.items():
        month_adjustments[month] = mean(vals) if vals else 0.0
    return month_adjustments


def _generate_forecast(dates: list[date], values: list[float], horizon_months: int) -> list[dict[str, Any]]:
    slope, intercept = _linear_trend(values)
    seasonality = _seasonal_adjustments(dates, values, slope, intercept)

    last_date = dates[-1]
    history_len = len(values)
    forecast_points: list[dict[str, Any]] = []
    for step in range(1, horizon_months + 1):
        future_date = _add_months(last_date, step)
        trend = intercept + (slope * (history_len + step - 1))
        seasonal = seasonality[future_date.month]
        predicted = max(0.0, trend + seasonal)
        forecast_points.append({"date": future_date, "demand": round(predicted, 2)})
    return forecast_points


def _serialize_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"date": item["date"].isoformat(), "demand": round(float(item["demand"]), 2)} for item in points]


def build_forecast(monthly_points: list[dict[str, Any]], horizon_months: int = 60) -> dict[str, Any]:
    dates = [item["date"] for item in monthly_points]
    values = [float(item["demand"]) for item in monthly_points]
    forecast_points = _generate_forecast(dates, values, horizon_months)

    recent_window = min(6, len(values))
    recent_avg = mean(values[-recent_window:])
    historic_avg = mean(values)
    historic_std = stdev(values) if len(values) > 1 else 0.0
    high_threshold = max(historic_avg + (0.5 * historic_std), recent_avg * 1.10)

    next_month_value = forecast_points[0]["demand"]
    next_5_month_values = [item["demand"] for item in forecast_points[:5]]
    next_5_year_values = [item["demand"] for item in forecast_points[:60]]

    next_month_high = next_month_value >= high_threshold
    next_5_months_avg = mean(next_5_month_values)
    next_5_months_high_count = sum(1 for value in next_5_month_values if value >= high_threshold)
    next_5_months_high = next_5_months_high_count >= 3 or next_5_months_avg >= (recent_avg * 1.10)

    first_year_avg = mean(next_5_year_values[:12]) if len(next_5_year_values) >= 12 else mean(next_5_year_values)
    last_year_avg = mean(next_5_year_values[-12:]) if len(next_5_year_values) >= 12 else mean(next_5_year_values)
    growth_percent = 0.0 if first_year_avg == 0 else ((last_year_avg - first_year_avg) / first_year_avg) * 100
    next_5_years_high = last_year_avg >= first_year_avg * 1.15

    historical = _serialize_points(monthly_points)
    forecast = _serialize_points(forecast_points)
    chart = {
        "labels": [item["date"] for item in historical + forecast],
        "historical_values": [item["demand"] for item in historical] + [None] * len(forecast),
        "forecast_values": [None] * len(historical) + [item["demand"] for item in forecast],
    }

    summary = {
        "high_demand_threshold": round(high_threshold, 2),
        "next_month": {
            "forecast": round(next_month_value, 2),
            "is_high_demand": bool(next_month_high),
        },
        "next_5_months": {
            "average_forecast": round(next_5_months_avg, 2),
            "months_high_demand": int(next_5_months_high_count),
            "is_high_demand": bool(next_5_months_high),
        },
        "next_5_years": {
            "year_1_average": round(first_year_avg, 2),
            "year_5_average": round(last_year_avg, 2),
            "growth_percent": round(growth_percent, 2),
            "is_high_demand": bool(next_5_years_high),
        },
    }

    return {
        "historical": historical,
        "forecast": forecast,
        "summary": summary,
        "chart": chart,
    }
