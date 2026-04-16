from datetime import date

from app.forecasting import build_forecast


def test_build_forecast_generates_horizons():
    monthly = []
    year = 2022
    month = 1
    for i in range(36):
        monthly.append({"date": date(year, month, 1), "demand": 100 + (i * 2)})
        month += 1
        if month > 12:
            month = 1
            year += 1

    result = build_forecast(monthly, horizon_months=60)

    assert len(result["historical"]) == 36
    assert len(result["forecast"]) == 60
    assert "next_month" in result["summary"]
    assert "next_5_months" in result["summary"]
    assert "next_5_years" in result["summary"]
