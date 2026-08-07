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
SIZE_ENDPOINT = "/api/funds/fonBuyuklukBazliBilgiGetir"

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


def _fetch_size_rows(
    kind: str = "YAT",
    start: date | None = None,
    end: date | None = None,
    timeout: int = 20,
) -> list:
    """Raw rows from the size (AUM) comparison endpoint for a [start, end] window.

    Confirmed live: sonPortfoyDegeri is the fund's total portfolio value at
    `end` (what TEFAS's UI labels "Fon Toplam Değer"), ilkPortfoyDegeri is
    the value at `start`, netGetiriOrani is the fund's own return (%) over
    that exact window, and sonPayAdedi/payAdetDegisim are share-count
    figures. Defaults to a 30-day window ending today when start/end aren't
    given (used for the current-size snapshot).
    """
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    payload = {
        "dil": "TR",
        "fonTipi": kind,
        "kurucuKodu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "islem": 1,
        "fonTurKod": None,
        "fonGrubu": None,
        "basTarih": start.strftime("%Y%m%d"),
        "bitTarih": end.strftime("%Y%m%d"),
        "calismaTipi": 1,
        "getiriOrani": "1",
    }
    try:
        resp = requests.post(
            f"{ROOT_URL}{SIZE_ENDPOINT}", json=payload, headers=HEADERS, timeout=timeout
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError):
        return []
    return body.get("resultList") or []


def fetch_fund_sizes(codes, timeout: int = 20) -> dict:
    """Current fund size (AUM) snapshot, keyed by fund code.

    Searches across all fund kinds (YAT/EMK/BYF) since a given code may not
    be a "YAT" fund. Values in TL. Returns {} entries only for codes found.
    """
    wanted = {c.upper() for c in codes}
    found = {}
    for kind in FUND_KINDS:
        if len(found) == len(wanted):
            break
        rows = _fetch_size_rows(kind, timeout=timeout)
        for row in rows:
            code = (row.get("fonKodu") or "").upper()
            if code in wanted and code not in found:
                size = row.get("sonPortfoyDegeri")
                if size is not None:
                    found[code] = {
                        "size": float(size),
                        "share_count": row.get("sonPayAdedi"),
                        "size_change_pct": row.get("portBuyuklukDegisim"),
                    }
    return found


# Calendar-day targets used only to pick a *starting point* to search
# backwards from within the known trading calendar (see _nearest_at_or_before).
# The actual boundary dates used in requests are always real trading days
# taken from `trading_dates`, never these raw day-counts.
CASH_FLOW_CALENDAR_DAYS = {
    "flow_weekly": 7,
    "flow_monthly": 30,
}


def _nearest_at_or_before(trading_dates: list[date], target: date) -> date | None:
    """Latest date in `trading_dates` (sorted ascending) that is <= target.
    Falls back to the earliest known date if target predates all of them."""
    candidates = [d for d in trading_dates if d <= target]
    return candidates[-1] if candidates else (trading_dates[0] if trading_dates else None)


def fetch_cash_flows(codes, trading_dates: list[date], timeout: int = 20) -> dict:
    """Estimated net subscription/redemption cash flow (TL) per fund.

    TEFAS doesn't publish cash flow directly. This estimates it from the
    size-comparison endpoint: the portfolio value change that ISN'T
    explained by the fund's own price return over the same window is
    attributed to net money in/out —
        flow = son_portfoy_degeri - ilk_portfoy_degeri * (1 + netGetiriOrani/100)
    A positive value means net inflows, negative means net outflows. This
    is an approximation (real flows can happen unevenly through the window,
    not just at the boundary), not an official TEFAS figure.

    `trading_dates` must be the sorted, ascending list of real trading days
    for these funds (e.g. taken from their own price histories) — it is
    what pins each window to an exact number of trading days instead of
    calendar days. This matters most for "daily": requesting the size
    endpoint with a start date a few calendar days back (to dodge
    weekends/holidays landing on an empty window) does NOT get snapped to
    "yesterday" by TEFAS — it returns the portfolio value literally at that
    earlier date, so a naive fixed day-count silently turns "daily" flow
    into a multi-day cumulative flow (e.g. 3-4x too large for a fund with
    sustained net inflows). Using the actual previous trading day instead
    guarantees an exact one-trading-day window every time.

    Returns {code: {"flow_daily":..., "flow_weekly":..., "flow_monthly":...,
    "flow_ytd":...}}, with a period key present only if it could be computed.
    """
    wanted = {c.upper() for c in codes}
    result = {c: {} for c in wanted}

    if not trading_dates:
        return result
    trading_dates = sorted(trading_dates)
    last_date = trading_dates[-1]
    prev_date = trading_dates[-2] if len(trading_dates) >= 2 else last_date

    period_starts = {"flow_daily": prev_date}
    for period_key, days_back in CASH_FLOW_CALENDAR_DAYS.items():
        period_starts[period_key] = _nearest_at_or_before(trading_dates, last_date - timedelta(days=days_back))

    for period_key, start in period_starts.items():
        found = set()
        for kind in FUND_KINDS:
            if len(found) == len(wanted):
                break
            rows = _fetch_size_rows(kind, start=start, end=last_date, timeout=timeout)
            for row in rows:
                code = (row.get("fonKodu") or "").upper()
                if code in wanted and code not in found:
                    found.add(code)
                    flow = _estimate_flow(row)
                    if flow is not None:
                        result[code][period_key] = flow

    # YTD: from Dec 31 of last year (so a fund with no activity yet in
    # January still gets a well-defined starting point) to the last known
    # trading day.
    ytd_start = date(last_date.year - 1, 12, 31)
    found = set()
    for kind in FUND_KINDS:
        if len(found) == len(wanted):
            break
        rows = _fetch_size_rows(kind, start=ytd_start, end=last_date, timeout=timeout)
        for row in rows:
            code = (row.get("fonKodu") or "").upper()
            if code in wanted and code not in found:
                found.add(code)
                flow = _estimate_flow(row)
                if flow is not None:
                    result[code]["flow_ytd"] = flow

    return result


def _estimate_flow(row: dict):
    ilk = row.get("ilkPortfoyDegeri")
    son = row.get("sonPortfoyDegeri")
    getiri = row.get("netGetiriOrani")
    if ilk is None or son is None or getiri is None:
        return None
    expected = ilk * (1 + getiri / 100)
    return son - expected


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
