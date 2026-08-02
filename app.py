"""TEFAS Fon Takip Paneli.

Streamlit dashboard for a fixed watchlist of TEFAS funds: daily/weekly/YTD
returns and current fund size (Büyüklük), plus an estimated net cash-flow
table computed on demand. TEFAS retired its old bulk API in 2026; the
current API no longer publishes historical asset-allocation data at all, so
that section shows a notice with a link to each fund's TEFAS page instead
of fabricated numbers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import streamlit as st

from tefas_client import (
    TefasFetchError,
    compute_returns,
    fetch_cash_flows,
    fetch_comparison_data,
    fetch_fund_prices,
    fetch_fund_sizes,
    fund_detail_url,
)

CACHE_TTL_SECONDS = 6 * 3600  # TEFAS prices update a few times a day, not every minute

FUND_CODES = [
    "PKZ", "TLY", "DFI", "LTL", "TP2", "PRY", "PHE",
    "MT2", "PBR", "PUK", "PCS", "VPS", "IIE",
]

POSITIVE = "#2CA858"
NEGATIVE = "#D6455D"
NEUTRAL_TEXT = "#6B7280"

st.set_page_config(page_title="TEFAS Fon Takip Paneli", layout="wide")

st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
    html, body, [class*="css"] {
        font-family: "Noto Sans", "notoSans Fallback", Arial, sans-serif;
    }
    h1 { font-size: 1.9rem !important; }
    h3 { font-size: 1.25rem !important; }
    p, li, .stMarkdown, .stCaption { font-size: 0.95rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_prices(code: str) -> pd.DataFrame:
    return fetch_fund_prices(code, months_back=12)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_comparison(codes: tuple) -> dict:
    return fetch_comparison_data(codes)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_sizes(codes: tuple) -> dict:
    return fetch_fund_sizes(codes)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_cash_flows(codes: tuple) -> dict:
    return fetch_cash_flows(codes)


def load_all_prices(codes: list) -> dict:
    """Fetch all fund price histories concurrently (each result is itself
    cached individually by load_prices, so a warm cache still returns fast).
    """
    results = {}
    errs = []
    with ThreadPoolExecutor(max_workers=min(8, len(codes))) as executor:
        future_to_code = {executor.submit(load_prices, code): code for code in codes}
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                results[code] = future.result()
            except TefasFetchError as exc:
                errs.append(exc)
    return results, errs


def pct(x):
    """Format a fraction (0.05 -> +5.00%)."""
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.2f}%"


def fmt_size(x):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.0f}"


def fmt_flow(x):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+,.0f}"


def color_for(x):
    if x is None or pd.isna(x):
        return NEUTRAL_TEXT
    return POSITIVE if x >= 0 else NEGATIVE


st.title("TEFAS Fon Takip Paneli")
st.caption(
    "Günlük ve haftalık getiriler fiyat geçmişinden hesaplanır; YTD "
    "TEFAS'ın kendi resmi karşılaştırma verisidir."
)

with st.sidebar:
    if st.button("Veriyi yenile (önbelleği temizle)"):
        load_prices.clear()
        load_comparison.clear()
        load_sizes.clear()
        load_cash_flows.clear()
        st.rerun()
    st.markdown("---")
    st.caption(
        "**Not:** TEFAS 2026'da eski toplu API'sini (BindHistoryInfo / "
        "BindHistoryAllocation) kapattı. Geçmiş varlık dağılımı verisi artık "
        "herkese açık bir uç noktadan alınamıyor — o bölüm her fonun resmi "
        "TEFAS sayfasına yönlendirme olarak gösteriliyor. Büyüklük, TEFAS'ın "
        "kendi güncel karşılaştırma verisinden (Fon Toplam Değer) alınır. "
        "Para giriş/çıkışı ise TEFAS'ta doğrudan yayınlanmıyor; büyüklük "
        "değişiminden fiyat getirisinin payı çıkarılarak **tahmin** edilir."
    )

selected = FUND_CODES
comparison = load_comparison(tuple(selected))
sizes = load_sizes(tuple(selected))

rows = []
with st.spinner("TEFAS'tan veri alınıyor..."):
    histories, errors = load_all_prices(selected)

for code in selected:
    df = histories.get(code)
    comp = comparison.get(code, {})
    size_info = sizes.get(code, {})
    if df is not None:
        r = compute_returns(df)
        title = (df.iloc[-1]["title"] if not df.empty else None) or comp.get("title")
        ytd = comp.get("r_ytd")
        ytd_fraction = ytd / 100 if ytd is not None else r["ytd_return"]
        rows.append(
            {
                "Kod": code,
                "Fon Adı": title or "—",
                "Son Fiyat": r["last_price"],
                "Büyüklük": size_info.get("size"),
                "Günlük": r["daily_return"],
                "Haftalık": r["weekly_return"],
                "YTD": ytd_fraction,
            }
        )

if errors:
    st.warning(
        "Şu fonlar için veri alınamadı (TEFAS erişilemedi ya da kod bulunamadı): "
        + ", ".join(e.code for e in errors)
    )

if not rows:
    st.error("Hiçbir fon için veri alınamadı.")
    st.stop()

summary = pd.DataFrame(rows)

st.subheader("Getiri Özeti")
colored_cols = ["Günlük", "Haftalık", "YTD"]
styled_summary = summary.style.format(
    {
        "Son Fiyat": lambda x: f"{x:.6f}" if pd.notna(x) else "—",
        "Büyüklük": fmt_size,
        "Günlük": pct,
        "Haftalık": pct,
        "YTD": pct,
    }
).apply(
    lambda s: [f"color: {color_for(v)}" for v in summary[s.name]] if s.name in colored_cols else [""] * len(s),
    axis=0,
).hide(axis="index")
# Static table: fixed column widths, no drag-to-resize, no column menu.
st.table(styled_summary)
st.caption(
    "Büyüklük, TEFAS'ın güncel Fon Toplam Değer verisidir (TL). YTD sütunu "
    "TEFAS'ın kendi resmi getiri hesaplamasıdır. Günlük ve Haftalık, fiyat "
    "geçmişinden ayrıca hesaplanır."
)
if not sizes:
    st.caption("Büyüklük verisi şu an TEFAS'tan okunamadı; tabloda '—' olarak görünür.")

st.markdown("---")
st.subheader("Para Giriş / Çıkışı (tahmini)")
st.caption(
    "TEFAS para giriş/çıkışını doğrudan yayınlamıyor. Aşağıdaki rakamlar, "
    "fon büyüklüğündeki değişimden fiyat getirisinin payı çıkarılarak "
    "hesaplanan bir **tahmindir** — resmi TEFAS verisi değildir. Bu hesap "
    "TEFAS'a ek istekler attığı için otomatik yüklenmez."
)

if "show_flows" not in st.session_state:
    st.session_state.show_flows = False
if st.button("Para giriş/çıkışını hesapla"):
    st.session_state.show_flows = True

if st.session_state.show_flows:
    with st.spinner("Para giriş/çıkışı hesaplanıyor..."):
        flows = load_cash_flows(tuple(selected))

    flow_rows = []
    for code in selected:
        f = flows.get(code, {})
        flow_rows.append(
            {
                "Kod": code,
                "Günlük": f.get("flow_daily"),
                "Haftalık": f.get("flow_weekly"),
                "Aylık": f.get("flow_monthly"),
                "YTD": f.get("flow_ytd"),
            }
        )
    flow_df = pd.DataFrame(flow_rows)
    flow_cols = ["Günlük", "Haftalık", "Aylık", "YTD"]
    styled_flows = flow_df.style.format({col: fmt_flow for col in flow_cols}).apply(
        lambda s: [f"color: {color_for(v)}" for v in flow_df[s.name]] if s.name in flow_cols else [""] * len(s),
        axis=0,
    ).hide(axis="index")
    # Static table: fixed column widths, no drag-to-resize, no column menu.
    st.table(styled_flows)
    if flow_df[flow_cols].isna().all(axis=None):
        st.caption("Para giriş/çıkışı şu an TEFAS'tan okunamadı; tabloda '—' olarak görünür.")

st.subheader("Varlık Dağılımı")
st.info(
    "TEFAS, fon bazında varlık dağılımı (hisse, tahvil, repo vb. oranları) "
    "verisini artık herkese açık bir API üzerinden yayınlamıyor. Güncel "
    "dağılım için ilgili fonun TEFAS sayfasını ziyaret edebilirsiniz."
)

link_cols = st.columns(4)
for i, code in enumerate(selected):
    with link_cols[i % 4]:
        st.markdown(f"**{code}** → [TEFAS sayfası]({fund_detail_url(code)})")

st.caption(f"Son güncelleme kontrolü: {date.today().isoformat()} · Kaynak: tefas.gov.tr")
