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

from tefas_client import TefasFetchError, compute_returns, fetch_fund_prices, fund_detail_url

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
    st.header("Filtre")
    selected = st.multiselect("Fonlar", FUND_CODES, default=FUND_CODES)
    if st.button("Veriyi yenile (önbelleği temizle)"):
        load_prices.clear()
        st.rerun()
    st.markdown("---")
    st.caption(
        "**Not:** TEFAS 2026'da eski toplu API'sini (BindHistoryInfo / "
        "BindHistoryAllocation) kapattı. Yeni API sadece günlük fiyat verisi "
        "sunuyor; geçmiş fon büyüklüğü, yatırımcı sayısı ve varlık dağılımı "
        "verileri artık herkese açık bir uç noktadan alınamıyor. Bu yüzden "
        "para giriş/çıkışı ve varlık dağılımı bölümleri, ilgili fonun resmi "
        "TEFAS sayfasına yönlendirme olarak gösteriliyor."
    )

if not selected:
    st.info("Soldan en az bir fon seçin.")
    st.stop()

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
                "Son Veri Tarihi": r["last_date"],
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


def returns_bar_chart(metric_col: str, title: str) -> go.Figure:
    data = summary.dropna(subset=[metric_col]).sort_values(metric_col)
    fig = go.Figure(
        go.Bar(
            x=data[metric_col] * 100,
            y=data["Kod"],
            orientation="h",
            marker_color=[POSITIVE if v >= 0 else NEGATIVE for v in data[metric_col]],
            text=[f"{v * 100:+.2f}%" for v in data[metric_col]],
            textposition="outside",
            hovertemplate="%{y}: %{x:.2f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Getiri (%)",
        yaxis_title=None,
        height=max(280, 32 * len(data) + 100),
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(zeroline=True, zerolinewidth=1, zerolinecolor=NEUTRAL_TEXT, gridcolor="rgba(128,128,128,0.15)")
    return fig


col1, col2, col3 = st.columns(3)
with col1:
    st.plotly_chart(returns_bar_chart("Günlük", "Günlük Getiri"), use_container_width=True)
with col2:
    st.plotly_chart(returns_bar_chart("Haftalık", "Haftalık Getiri"), use_container_width=True)
with col3:
    st.plotly_chart(returns_bar_chart("YTD", "Yıl Başından Bugüne (YTD) Getiri"), use_container_width=True)

st.subheader("Fiyat Geçmişi (son 12 ay)")
fig = go.Figure()
for code in selected:
    df = histories.get(code)
    if df is None or df.empty:
        continue
    indexed = df["price"] / df["price"].iloc[0] * 100
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=indexed,
            mode="lines",
            name=code,
            line=dict(color=COLOR_MAP.get(code), width=2),
            hovertemplate=f"{code}" + " %{x}: %{y:.2f}<extra></extra>",
        )
    )
fig.update_layout(
    yaxis_title="Endeks (başlangıç = 100)",
    xaxis_title=None,
    height=450,
    margin=dict(l=10, r=10, t=20, b=10),
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
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
