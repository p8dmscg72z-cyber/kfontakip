"""TEFAS Fon Takip Paneli.

Streamlit dashboard for a fixed watchlist of TEFAS funds: shows daily / weekly /
YTD returns computed from the public TEFAS price API. TEFAS retired its old
bulk API in 2026; the current API no longer publishes historical AUM /
investor-count / asset-allocation data, so those two sections show a notice
with a link to each fund's TEFAS page instead of fabricated numbers.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas_client import (
    TefasFetchError,
    compute_returns,
    fetch_fund_prices,
    fetch_fund_sizes,
    fund_detail_url,
)

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


@st.cache_data(ttl=3600, show_spinner=False)
def load_prices(code: str) -> pd.DataFrame:
    return fetch_fund_prices(code, months_back=12)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sizes(codes: tuple) -> dict:
    return fetch_fund_sizes(codes)


def fmt_size(x):
    if x is None or pd.isna(x):
        return "—"
    if x >= 1e9:
        return f"{x / 1e9:,.2f} Milyar TL"
    if x >= 1e6:
        return f"{x / 1e6:,.2f} Milyon TL"
    return f"{x:,.0f} TL"


def pct(x):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.2f}%"


def color_for(x):
    if x is None or pd.isna(x):
        return NEUTRAL_TEXT
    return POSITIVE if x >= 0 else NEGATIVE


st.title("TEFAS Fon Takip Paneli")
st.caption(
    "Günlük, haftalık ve yıl başından bugüne (YTD) getiriler; TEFAS'ın güncel "
    "fon fiyatı API'sinden hesaplanır."
)

with st.sidebar:
    if st.button("Veriyi yenile (önbelleği temizle)"):
        load_prices.clear()
        load_sizes.clear()
        st.rerun()
    st.markdown("---")
    st.caption(
        "**Not:** TEFAS 2026'da eski toplu API'sini (BindHistoryInfo / "
        "BindHistoryAllocation) kapattı. Geçmiş para giriş/çıkışı ve varlık "
        "dağılımı verileri artık herkese açık bir uç noktadan alınamıyor. Bu "
        "yüzden ilgili bölümler, her fonun resmi TEFAS sayfasına yönlendirme "
        "olarak gösteriliyor. Büyüklük sütunu, TEFAS'ın anlık karşılaştırma "
        "verisinden en iyi çaba (best-effort) ile okunuyor."
    )

selected = FUND_CODES
sizes = load_sizes(tuple(selected))

rows = []
histories = {}
errors = []
with st.spinner("TEFAS'tan fiyat verisi alınıyor..."):
    for code in selected:
        try:
            df = load_prices(code)
        except TefasFetchError as exc:
            errors.append(exc)
            continue
        histories[code] = df
        r = compute_returns(df)
        title = df.iloc[-1]["title"] if not df.empty else None
        rows.append(
            {
                "Kod": code,
                "Fon Adı": title or "—",
                "Son Fiyat": r["last_price"],
                "Büyüklük": sizes.get(code),
                "Günlük": r["daily_return"],
                "Haftalık": r["weekly_return"],
                "YTD": r["ytd_return"],
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
display_df["Büyüklük"] = summary["Büyüklük"].map(fmt_size)
for col in ["Günlük", "Haftalık", "YTD"]:
    display_df[col] = summary[col].map(pct)

st.dataframe(
    display_df.style.apply(
        lambda s: [f"color: {color_for(v)}" for v in summary[s.name]] if s.name in ("Günlük", "Haftalık", "YTD") else [""] * len(s),
        axis=0,
    ),
    hide_index=True,
    use_container_width=True,
)


if not sizes:
    st.caption(
        "Büyüklük verisi şu an TEFAS'tan okunamadı; tabloda '—' olarak görünür."
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
