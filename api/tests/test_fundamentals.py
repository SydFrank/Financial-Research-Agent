import pandas as pd

from app.data.fundamentals import identity_failures, normalise, source_symbol


def statements(**overrides) -> dict[str, pd.DataFrame]:
    row = {
        "REPORT_DATE": "2025-12-31 00:00:00",
        "NOTICE_DATE": "2026-04-17 00:00:00",
        "UPDATE_DATE": "2026-04-17 00:00:00",
        "CURRENCY": "CNY",
        "OPERATE_INCOME": 1.0e11,
        "RESEARCH_EXPENSE": float("nan"),
    } | overrides
    quarterly = row | {"REPORT_DATE": "2025-09-30 00:00:00", "OPERATE_INCOME": 7.0e10}
    return {"profit": pd.DataFrame([row, quarterly])}


def by_metric(facts: list[dict]) -> dict[str, dict]:
    return {f["metric"]: f for f in facts}


def test_source_symbol_adds_exchange_prefix():
    assert source_symbol("600519") == "SH600519"
    assert source_symbol("000333") == "SZ000333"


def test_keeps_annual_figures_only():
    facts = normalise("600519", statements(), [2025], "t")
    revenue = [f for f in facts if f["metric"] == "operating_revenue"]
    assert len(revenue) == 1
    assert revenue[0]["value"] == 1.0e11
    assert revenue[0]["period_end"] == "2025-12-31"
    assert revenue[0]["unit"] == "元"


def test_skips_years_not_requested():
    assert normalise("600519", statements(), [2024], "t") == []


def test_missing_value_is_skipped_not_stored_as_zero():
    assert "rd_expense" not in by_metric(normalise("600519", statements(), [2025], "t"))


def test_non_cny_rows_are_skipped():
    assert normalise("600519", statements(CURRENCY="USD"), [2025], "t") == []


def test_flags_values_updated_after_first_disclosure():
    original = by_metric(normalise("600519", statements(), [2025], "t"))["operating_revenue"]
    assert original["possibly_restated"] is False
    later = statements(UPDATE_DATE="2027-04-10 00:00:00")
    restated = by_metric(normalise("600519", later, [2025], "t"))["operating_revenue"]
    assert restated["possibly_restated"] is True
    assert restated["first_disclosed_at"] == "2026-04-17"


def fact(metric: str, value: float) -> dict:
    return {"symbol": "600519", "fiscal_year": 2025, "metric": metric, "value": value}


def test_identity_holds():
    facts = [fact("total_assets", 300.0), fact("total_liabilities", 50.0), fact("total_equity", 250.0)]
    assert identity_failures(facts) == []


def test_identity_violation_is_reported():
    facts = [fact("total_assets", 300.0), fact("total_liabilities", 50.0), fact("total_equity", 200.0)]
    assert len(identity_failures(facts)) == 1


def test_missing_balance_sheet_totals_are_reported():
    assert identity_failures([fact("total_assets", 300.0)]) == ["600519 2025: balance sheet totals missing"]
