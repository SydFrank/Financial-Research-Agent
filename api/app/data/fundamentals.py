"""Fetch structured financial statements via AKShare (Eastmoney data) and normalise them.

Usage, from the api/ directory:
    uv run python -m app.data.fundamentals --years 2023 2024 2025

Two layers are written:
- raw:        data/raw/fundamentals/<symbol>_<statement>_<YYYYMMDD>.csv
              exactly what the source returned on that day, kept so results can be
              reproduced and errors traced even if the source changes later
- normalised: data/processed/fundamentals.jsonl
              one fact per line, our metric names, unit 元, annual reports only
"""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import akshare as ak
import pandas as pd
import yaml

CHINA_TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPANIES_FILE = REPO_ROOT / "config" / "companies.yaml"
RAW_DIR = REPO_ROOT / "data" / "raw" / "fundamentals"
PROCESSED_FILE = REPO_ROOT / "data" / "processed" / "fundamentals.jsonl"

REQUEST_INTERVAL_S = 1.0
SOURCE = "akshare:eastmoney"

STATEMENT_FETCHERS = {
    "profit": ak.stock_profit_sheet_by_report_em,
    "balance": ak.stock_balance_sheet_by_report_em,
    "cash": ak.stock_cash_flow_sheet_by_report_em,
}

# our metric id -> (statement, source field, Chinese label)
METRICS: dict[str, tuple[str, str, str]] = {
    "total_operating_revenue": ("profit", "TOTAL_OPERATE_INCOME", "营业总收入"),
    "operating_revenue": ("profit", "OPERATE_INCOME", "营业收入"),
    "operating_cost": ("profit", "OPERATE_COST", "营业成本"),
    "selling_expense": ("profit", "SALE_EXPENSE", "销售费用"),
    "admin_expense": ("profit", "MANAGE_EXPENSE", "管理费用"),
    "rd_expense": ("profit", "RESEARCH_EXPENSE", "研发费用"),
    "net_profit": ("profit", "NETPROFIT", "净利润"),
    "parent_net_profit": ("profit", "PARENT_NETPROFIT", "归属于母公司股东的净利润"),
    "total_assets": ("balance", "TOTAL_ASSETS", "资产总计"),
    "total_liabilities": ("balance", "TOTAL_LIABILITIES", "负债合计"),
    "total_equity": ("balance", "TOTAL_EQUITY", "所有者权益合计"),
    "parent_equity": ("balance", "TOTAL_PARENT_EQUITY", "归属于母公司股东的权益"),
    "net_cash_operating": ("cash", "NETCASH_OPERATE", "经营活动产生的现金流量净额"),
    "net_cash_investing": ("cash", "NETCASH_INVEST", "投资活动产生的现金流量净额"),
    "net_cash_financing": ("cash", "NETCASH_FINANCE", "筹资活动产生的现金流量净额"),
}

IDENTITY_TOLERANCE = 0.005  # assets = liabilities + equity, within 0.5%


# --- pure helpers (unit-tested) -----------------------------------------------

def source_symbol(symbol: str) -> str:
    """Eastmoney wants an exchange prefix: SH for Shanghai, SZ for Shenzhen."""
    return ("SH" if symbol.startswith("6") else "SZ") + symbol


def normalise(symbol: str, statements: dict[str, pd.DataFrame], years: list[int], fetched_at: str) -> list[dict]:
    """Turn raw statements into one fact per (metric, fiscal year).

    Only annual reports for the requested years are kept, and only consolidated
    figures in CNY. Missing values are skipped rather than stored as zero.
    """
    facts = []
    for metric, (statement, field, label) in METRICS.items():
        df = statements.get(statement)
        if df is None or field not in df.columns:
            continue
        for _, row in df.iterrows():
            period_end = str(row["REPORT_DATE"])[:10]
            year = int(period_end[:4])
            if not period_end.endswith("-12-31") or year not in years:
                continue
            if row.get("CURRENCY", "CNY") != "CNY" or pd.isna(row[field]):
                continue
            first_disclosed = str(row["NOTICE_DATE"])[:10]
            updated = str(row["UPDATE_DATE"])[:10]
            facts.append({
                "symbol": symbol,
                "metric": metric,
                "metric_label": label,
                "fiscal_year": year,
                "period_end": period_end,
                "value": float(row[field]),
                "unit": "元",
                # the date the report was first published
                "first_disclosed_at": first_disclosed,
                # the date the source last changed this row; a later date means
                # the value may have been restated by a later report
                "source_updated_at": updated,
                "possibly_restated": updated > first_disclosed,
                "source": SOURCE,
                "source_field": f"{statement}.{field}",
                "fetched_at": fetched_at,
            })
    return facts


def identity_failures(facts: list[dict]) -> list[str]:
    """Check assets = liabilities + equity for every company and year."""
    by_key: dict[tuple[str, int], dict[str, float]] = {}
    for f in facts:
        by_key.setdefault((f["symbol"], f["fiscal_year"]), {})[f["metric"]] = f["value"]
    failures = []
    for (symbol, year), m in sorted(by_key.items()):
        if not {"total_assets", "total_liabilities", "total_equity"} <= m.keys():
            failures.append(f"{symbol} {year}: balance sheet totals missing")
            continue
        gap = abs(m["total_assets"] - (m["total_liabilities"] + m["total_equity"]))
        if gap > IDENTITY_TOLERANCE * abs(m["total_assets"]):
            failures.append(f"{symbol} {year}: assets differ from liabilities + equity by {gap:,.0f} 元")
    return failures


# --- main -----------------------------------------------------------------------

def fetch_raw(symbol: str, day: str) -> dict[str, pd.DataFrame]:
    """Fetch the three statements and keep a dated copy of each, exactly as returned."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    statements = {}
    for statement, fetch in STATEMENT_FETCHERS.items():
        time.sleep(REQUEST_INTERVAL_S)
        df = fetch(symbol=source_symbol(symbol))
        df.to_csv(RAW_DIR / f"{symbol}_{statement}_{day}.csv", index=False, encoding="utf-8")
        statements[statement] = df
    return statements


def run(years: list[int]) -> None:
    companies = yaml.safe_load(COMPANIES_FILE.read_text(encoding="utf-8"))["companies"]
    now = datetime.now(CHINA_TZ)
    day, fetched_at = now.strftime("%Y%m%d"), now.isoformat(timespec="seconds")

    facts: list[dict] = []
    for company in companies:
        symbol, name = company["symbol"], company["name"]
        try:
            statements = fetch_raw(symbol, day)
        except Exception as exc:  # one company's failure must not stop the others
            print(f"FAIL   {name}: {exc}")
            continue
        if company["financial"]:
            print(f"raw    {name} (financial company: raw kept, not normalised yet)")
            continue
        company_facts = normalise(symbol, statements, years, fetched_at)
        facts.extend(company_facts)
        print(f"ok     {name}: {len(company_facts)} facts")

    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        for fact in facts:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")

    restated = sum(f["possibly_restated"] for f in facts)
    print(f"\n{len(facts)} facts written, {restated} possibly restated by a later report")
    failures = identity_failures(facts)
    print("identity check: " + ("all passed" if not failures else f"{len(failures)} failed"))
    for failure in failures:
        print("  " + failure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", type=int, nargs="+", required=True)
    run(parser.parse_args().years)
