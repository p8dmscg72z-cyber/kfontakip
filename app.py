"""TEFAS Fon Takip Paneli.

Streamlit dashboard for a fixed watchlist of TEFAS funds: daily/weekly returns
computed from the public price API, plus YTD/1A/3A/6A/1Y returns straight from
TEFAS's own comparison-table endpoint. TEFAS retired its old bulk API in 2026;
the current API no longer publishes historical AUM/investor-count/
asset-allocation data at all (confirmed via a live sample of the comparison
endpoint), so those sections show a notice with a link to each fund's TEFAS
page instead of fabricated numbers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas_client import (
    TefasFetchError,
    compute_returns,
    fetch_comparison_data,
    fetch_fund_prices,
    fund_detail_url,
)

CACHE_TTL_SECONDS = 6 * 3600  # TEFAS prices update a few times a day, not every minute

FUND_CODES = [
    "PKZ", "TLY", "DFI", "LTL", "TP2", "PRY", "PHE",
    "MT2", "PBR", "PUK", "PCS", "VPS", "IIE",
]

# Fixed categorical order — never re-sorted by value, so a fund keeps its
# color across reruns and filters.
FUND_COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#B279A2", "#E45756",
    "#72B7B2", "#EECA3B", "#9D755D", "#BAB0AC", "#FF9DA6",
    "#9C755F", "#5254A3", "#8CA252",
]
COLOR_MAP = dict(zip(FUND_CODES, FUND_COLORS))

POSITIVE = "#2CA858"
NEGATIVE = "#D6455D"
NEUTRAL_TEXT = "#6B7280"

st.set_page_config(page_title="TEFAS Fon Takip Paneli", layout="wide")


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_prices(code: str) -> pd.DataFrame:
    return fetch_fund_prices(code, months_back=12)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_comparison(codes: tuple) -> dict:
    return fetch_comparison_data(codes)


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


def pct_already(x):
    """Format a value that's already a percentage (11.03 -> +11.03%)."""
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+.2f}%"


def color_for(x):
    if x is None or pd.isna(x):
        return NEUTRAL_TEXT
    return POSITIVE if x >= 0 else NEGATIVE


st.title("TEFAS Fon Takip Paneli")
st.caption(
    "Günlük ve haftalık getiriler fiyat geçmişinden hesaplanır; YTD ve diğer "
    "dönemsel getiriler TEFAS'ın kendi resmi karşılaştırma verisidir."
)

with st.sidebar:
    if st.button("Veriyi yenile (önbelleği temizle)"):
        load_prices.clear()
        load_comparison.clear()
        st.rerun()
    st.markdown("---")
    st.caption(
        "**Not:** TEFAS 2026'da eski toplu API'sini (BindHistoryInfo / "
        "BindHistoryAllocation) kapattı. Geçmiş fon büyüklüğü/para giriş-çıkışı "
        "ve varlık dağılımı verileri artık herkese açık bir uç noktadan "
        "alınamıyor — bu yüzden ilgili bölüm her fonun resmi TEFAS sayfasına "
        "yönlendirme olarak gösteriliyor."
    )

selected = FUND_CODES
comparison = load_comparison(tuple(selected))

rows = []
with st.spinner("TEFAS'tan veri alınıyor..."):
    histories, errors = load_all_prices(selected)

for code in selected:
    df = histories.get(code)
    comp = comparison.get(code, {})
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
                "Günlük": r["daily_return"],
                "Haftalık": r["weekly_return"],
                "YTD": ytd_fraction,
                "1 Ay": comp.get("r_1a"),
                "3 Ay": comp.get("r_3a"),
                "6 Ay": comp.get("r_6a"),
                "1 Yıl": comp.get("r_1y"),
                "Risk": comp.get("risk"),
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
display_df = summary.copy()
display_df["Son Fiyat"] = display_df["Son Fiyat"].map(lambda x: f"{x:.6f}" if pd.notna(x) else "—")
for col in ["Günlük", "Haftalık", "YTD"]:
    display_df[col] = summary[col].map(pct)
for col in ["1 Ay", "3 Ay", "6 Ay", "1 Yıl"]:
    display_df[col] = summary[col].map(pct_already)
display_df["Risk"] = summary["Risk"].map(lambda x: x if x else "—")

colored_cols = ["Günlük", "Haftalık", "YTD", "1 Ay", "3 Ay", "6 Ay", "1 Yıl"]
st.dataframe(
    display_df.style.apply(
        lambda s: [f"color: {color_for(v)}" for v in summary[s.name]] if s.name in colored_cols else [""] * len(s),
        axis=0,
    ),
    hide_index=True,
    use_container_width=True,
)
st.caption(
    "YTD, 1 Ay, 3 Ay, 6 Ay ve 1 Yıl sütunları TEFAS'ın kendi resmi getiri "
    "hesaplamasıdır. Günlük ve Haftalık, fiyat geçmişinden ayrıca hesaplanır."
)

st.subheader("Fiyat Geçmişi (son 12 ay)")
chosen_code = st.selectbox("Fon seçin", selected, index=0)
chosen_df = histories.get(chosen_code)

if chosen_df is None or chosen_df.empty:
    st.info(f"{chosen_code} için fiyat geçmişi bulunamadı.")
else:
    fig = go.Figure(
        go.Scatter(
            x=chosen_df["date"],
            y=chosen_df["price"],
            mode="lines",
            name=chosen_code,
            line=dict(color=COLOR_MAP.get(chosen_code, "#4C78A8"), width=2),
            hovertemplate="%{x}: %{y:.6f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"{chosen_code} — Fiyat",
        yaxis_title="Fiyat (TL)",
        xaxis_title=None,
        height=450,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.subheader("Para Giriş / Çıkışı")
st.info(
    "TEFAS, fon bazında geçmiş para giriş/çıkışı (fon büyüklüğü değişimi) "
    "verisini artık herkese açık bir API üzerinden yayınlamıyor. Güncel "
    "rakamlar için ilgili fonun TEFAS sayfasını ziyaret edebilirsiniz."
)

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
