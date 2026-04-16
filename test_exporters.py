from app.exporters import build_forecast_csv_bytes, build_forecast_pdf_bytes, make_safe_filename


def _sample_payload():
    historical = [
        {"date": "2025-01-01", "demand": 100.0},
        {"date": "2025-02-01", "demand": 110.0},
    ]
    forecast = [
        {"date": "2025-03-01", "demand": 118.5},
        {"date": "2025-04-01", "demand": 123.2},
    ]
    summary = {
        "high_demand_threshold": 121.0,
        "next_month": {"forecast": 118.5, "is_high_demand": False},
        "next_5_months": {"average_forecast": 125.6, "months_high_demand": 2, "is_high_demand": False},
        "next_5_years": {"year_1_average": 130.1, "year_5_average": 175.2, "growth_percent": 34.66, "is_high_demand": True},
    }
    return historical, forecast, summary


def test_csv_export_contains_expected_sections():
    historical, forecast, summary = _sample_payload()
    csv_bytes = build_forecast_csv_bytes(
        product_name="Phone X",
        historical=historical,
        forecast=forecast,
        summary=summary,
        created_at="2026-04-06T00:00:00+00:00",
    )
    csv_text = csv_bytes.decode("utf-8")
    assert "Product Name,Phone X" in csv_text
    assert "Summary" in csv_text
    assert "Historical Data" in csv_text
    assert "Forecast Data" in csv_text


def test_pdf_export_starts_with_pdf_header():
    historical, forecast, summary = _sample_payload()
    pdf_bytes = build_forecast_pdf_bytes(
        product_name="Phone X",
        historical=historical,
        forecast=forecast,
        summary=summary,
        created_at="2026-04-06T00:00:00+00:00",
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_filename_sanitization():
    assert make_safe_filename("Phone X / 2026 report.pdf") == "Phone_X_2026_report.pdf"
