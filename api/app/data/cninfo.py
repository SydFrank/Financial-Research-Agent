"""Download annual reports from cninfo (巨潮资讯网), the CSRC-designated disclosure platform.

Usage, from the api/ directory:
    uv run python -m app.data.cninfo --years 2023 2024 2025

Files go to data/raw/filings/<symbol>/<symbol>_<year>_annual.pdf, and every
download is recorded in data/raw/filings/manifest.json with its source,
publication time and SHA-256. Re-running skips files already downloaded intact.
"""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

BASE_URL = "http://www.cninfo.com.cn"
STATIC_URL = "http://static.cninfo.com.cn/"
CHINA_TZ = timezone(timedelta(hours=8))

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPANIES_FILE = REPO_ROOT / "config" / "companies.yaml"
OUT_DIR = REPO_ROOT / "data" / "raw" / "filings"
MANIFEST_FILE = OUT_DIR / "manifest.json"

REQUEST_INTERVAL_S = 1.0  # pause between requests, to be polite to the server
MAX_ATTEMPTS = 3
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Announcements whose title contains any of these are not the full annual report.
EXCLUDED_TITLE_WORDS = ("摘要", "英文", "取消", "提示性公告", "补充", "问询")


# --- pure helpers (unit-tested) ---------------------------------------------

def exchange_column(symbol: str) -> str:
    """cninfo's exchange code: Shanghai codes start with 6, the rest are Shenzhen."""
    return "sse" if symbol.startswith("6") else "szse"


def clean_title(title: str) -> str:
    """Strip the <em> highlight tags cninfo puts around search matches."""
    return re.sub(r"<[^>]+>", "", title).strip()


def pick_full_report(announcements: list[dict], fiscal_year: int) -> dict | None:
    """Pick the full annual report for a fiscal year from a list of announcements.

    Keeps titles naming that year's annual report, drops summaries, English
    versions, cancelled notices and the like. When a report was re-issued
    (for example a corrected version), the most recent one wins.

    Companies phrase the title either as "2025年年度报告" or "2025年度报告".
    """
    targets = (f"{fiscal_year}年年度报告", f"{fiscal_year}年度报告")
    candidates = [
        a for a in announcements
        if any(t in clean_title(a["announcementTitle"]) for t in targets)
        and not any(w in clean_title(a["announcementTitle"]) for w in EXCLUDED_TITLE_WORDS)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a["announcementTime"])


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- network ------------------------------------------------------------------

def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Send a request, retrying transient failures with increasing waits."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        time.sleep(REQUEST_INTERVAL_S)
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def find_org_id(client: httpx.Client, symbol: str) -> str:
    """cninfo identifies companies by an orgId; look it up from the stock code."""
    response = _request(
        client, "POST", f"{BASE_URL}/new/information/topSearch/query",
        data={"keyWord": symbol, "maxNum": 10},
    )
    for hit in response.json():
        if hit.get("code") == symbol:
            return hit["orgId"]
    raise LookupError(f"no cninfo orgId found for {symbol}")


def query_annual_reports(client: httpx.Client, symbol: str, org_id: str, fiscal_year: int) -> list[dict]:
    """Annual reports are published in the year after the fiscal year they cover."""
    publish_year = fiscal_year + 1
    response = _request(
        client, "POST", f"{BASE_URL}/new/hisAnnouncement/query",
        data={
            "stock": f"{symbol},{org_id}",
            "tabName": "fulltext",
            "pageSize": 50,
            "pageNum": 1,
            "column": exchange_column(symbol),
            "category": "category_ndbg_szsh;",
            "seDate": f"{publish_year}-01-01~{publish_year}-12-31",
            "isHLtitle": "false",
        },
    )
    return response.json().get("announcements") or []


def download(client: httpx.Client, url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    time.sleep(REQUEST_INTERVAL_S)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with partial.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    partial.rename(path)  # only a complete download gets the final name


# --- main ---------------------------------------------------------------------

def load_manifest() -> dict[str, dict]:
    if MANIFEST_FILE.exists():
        return {r["path"]: r for r in json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))}
    return {}


def save_manifest(records: dict[str, dict]) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records.values(), key=lambda r: (r["symbol"], r["fiscal_year"]))
    MANIFEST_FILE.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def run(years: list[int]) -> None:
    companies = yaml.safe_load(COMPANIES_FILE.read_text(encoding="utf-8"))["companies"]
    manifest = load_manifest()

    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for company in companies:
            symbol, name = company["symbol"], company["name"]
            org_id = find_org_id(client, symbol)
            for year in years:
                path = OUT_DIR / symbol / f"{symbol}_{year}_annual.pdf"
                key = str(path.relative_to(REPO_ROOT))
                known = manifest.get(key)
                if known and path.exists() and sha256_of(path) == known["sha256"]:
                    print(f"skip   {name} {year} (already downloaded)")
                    continue

                report = pick_full_report(query_annual_reports(client, symbol, org_id, year), year)
                if report is None:
                    print(f"MISS   {name} {year}: no full annual report found")
                    continue

                url = STATIC_URL + report["adjunctUrl"]
                download(client, url, path)
                published_at = datetime.fromtimestamp(report["announcementTime"] / 1000, CHINA_TZ)
                manifest[key] = {
                    "symbol": symbol,
                    "name": name,
                    "fiscal_year": year,
                    "title": clean_title(report["announcementTitle"]),
                    "announcement_id": report["announcementId"],
                    "published_at": published_at.isoformat(),
                    "source_url": url,
                    "path": key,
                    "sha256": sha256_of(path),
                    "size_bytes": path.stat().st_size,
                    "downloaded_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                }
                save_manifest(manifest)  # save after every file, so a crash loses nothing
                print(f"ok     {name} {year} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", type=int, nargs="+", required=True)
    run(parser.parse_args().years)
