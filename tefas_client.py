"""Minimal client for the public tefas.gov.tr fund-price JSON API.

TEFAS retired its old bulk endpoints (BindHistoryInfo / BindHistoryAllocation)
in 2026. The current API (`/api/funds/fonFiyatBilgiGetir`) only publishes
per-fund daily price history — it no longer exposes historical AUM, investor
counts, or asset-allocation breakdowns. This client only fetches what the
API still provides: daily fund prices, used to compute returns.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd
import requests

ROOT_URL = "https://www.tefas.gov.tr"
PRICE_ENDPOINT = "/api/funds/fonFiyatBilgiGetir"
LIST_ENDPOINT = "/api/funds/fonGetiriBazliBilgiGetir"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}

# The API only accepts these look-back windows (months).
VALID_PERIODS = (1, 3, 6, 12, 36, 60)

FUND_DETAIL_URL_TMPL = "https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={code}"


def fund_detail_url(code: str) -> str:
    return FUND_DETAIL_URL_TMPL.format(code=code)


def _snap_period(months_needed: int) -> int:
    for period in VALID_PERIODS:
        if period >= months_needed:
            return period
    return VALID_PERIODS[-1]


def fetch_fund_prices(code: str, months_back: int = 12, timeout: int = 20) -> pd.DataFrame:
    """Fetch daily price history for a single fund code.

    Returns a DataFrame with columns: date, code, title, price
    (sorted ascending by date). Empty DataFrame on any failure.
    """
    period = _snap_period(months_back)
    payload = {"fonKodu": code.upper(), "dil": "TR", "periyod": period}
    try:
        resp = requests.post(
            f"{ROOT_URL}{PRICE_ENDPOINT}", json=payload, headers=HEADERS, timeout=timeout
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TefasFetchError(code, str(exc)) from exc

    rows = body.get("resultList") or []
    if not rows:
        return pd.DataFrame(columns=["date", "code", "title", "price"])

    records = []
    for row in rows:
        raw_date = row.get("tarih")
        try:
            if isinstance(raw_date, str):
                d = datetime.strptime(raw_date, "%Y-%m-%d").date()
            else:
                continue
        except ValueError:
            continue
        price = row.get("fiyat")
        if price is None:
            continue
        records.append(
            {
                "date": d,
                "code": row.get("fonKodu", code.upper()),
                "title": row.get("fonUnvan"),
                "price": float(price),
            }
        )

    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df
    df = df.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    return df


FUND_KINDS = ("YAT", "EMK", "BYF")


def _fetch_list_rows(kind: str = "YAT", timeout: int = 20) -> list:
    """Raw rows from the comparison-table endpoint, one dict per fund.

    Returns [] on any failure. Kept separate from fetch_fund_sizes so a
    debug view can inspect the untouched field names/values.
    """
    payload = {
        "dil": "TR",
        "fonTipi": kind,
        "kurucuKodu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "islem": 1,
        "fonTurKod": None,
        "fonGrubu": None,
        "donemGetiri1a": "1",
        "donemGetiri3a": "1",
        "donemGetiri6a": "1",
        "donemGetiri1y": "1",
        "donemGetiriyb": "1",
        "donemGetiri3y": "1",
        "donemGetiri5y": "1",
        "basTarih": None,
        "bitTarih": None,
        "calismaTipi": 2,
        "getiriOrani": "1",
    }
    try:
        resp = requests.post(
            f"{ROOT_URL}{LIST_ENDPOINT}", json=payload, headers=HEADERS, timeout=timeout
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError):
        return []
    return body.get("resultList") or []


def fetch_comparison_data(codes, timeout: int = 20) -> dict:
    """TEFAS's own official period returns for the given fund codes.

    Confirmed available fields (from a live sample of this endpoint):
    fonUnvan, fonTurAciklama, riskDegeri, and period returns getiri1a/3a/6a/1y,
    getiriyb (year-to-date), getiri3y/5y — all as percentages, e.g. 11.03
    means +11.03%. No AUM/size field is present on this endpoint.

    Searches across all three fund kinds (YAT/EMK/BYF) since a given code
    may not be a "YAT" fund. Returns {} entries only for codes actually found.
    """
    wanted = {c.upper() for c in codes}
    found = {}
    for kind in FUND_KINDS:
        if len(found) == len(wanted):
            break
        rows = _fetch_list_rows(kind, timeout)
        for row in rows:
            code = (row.get("fonKodu") or "").upper()
            if code in wanted and code not in found:
                found[code] = {
                    "title": row.get("fonUnvan"),
                    "fund_type": row.get("fonTurAciklama"),
                    "risk": row.get("riskDegeri"),
                    "r_1a": row.get("getiri1a"),
                    "r_3a": row.get("getiri3a"),
                    "r_6a": row.get("getiri6a"),
                    "r_1y": row.get("getiri1y"),
                    "r_ytd": row.get("getiriyb"),
                    "r_3y": row.get("getiri3y"),
                    "r_5y": row.get("getiri5y"),
                }
    return found


class TefasFetchError(RuntimeError):
    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


def _price_on_or_before(df: pd.DataFrame, target: date):
    subset = df[df["date"] <= target]
    if subset.empty:
        return None
    return subset.iloc[-1]


def compute_returns(df: pd.DataFrame) -> dict:
    """Compute daily / weekly / YTD returns (as fractions) from a price history.

    Uses the latest available price as the reference point and looks back to
    the nearest trading day at/before each target date.
    """
    result = {
        "last_date": None,
        "last_price": None,
        "daily_return": None,
        "weekly_return": None,
        "ytd_return": None,
    }
    if df is None or df.empty:
        return result

    last_row = df.iloc[-1]
    last_date = last_row["date"]
    last_price = last_row["price"]
    result["last_date"] = last_date
    result["last_price"] = last_price

    if len(df) >= 2:
        prev_price = df.iloc[-2]["price"]
        if prev_price:
            result["daily_return"] = last_price / prev_price - 1

    week_target = last_date - timedelta(days=7)
    week_row = _price_on_or_before(df.iloc[:-1], week_target)
    if week_row is not None and week_row["price"]:
        result["weekly_return"] = last_price / week_row["price"] - 1

    year_start_target = date(last_date.year - 1, 12, 31)
    ytd_row = _price_on_or_before(df, year_start_target)
    if ytd_row is not None and ytd_row["price"]:
        result["ytd_return"] = last_price / ytd_row["price"] - 1

    return result
