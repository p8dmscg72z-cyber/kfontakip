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

CACHE_TTL_SECONDS = 1 * 3600

FUND_GROUPS = {
    "Exotics": [
        "PKZ", "TLY", "DFI", "LTL", "TP2", "PRY", "PHE",
        "MT2", "PBR", "PUK", "PCS", "VPS", "IIE",
    ],
    "Altın Emeklilik": ["AMZ", "CFA", "GRA", "BNA", "NHA", "BGL", "AEA"],
}

POSITIVE = "#2CA858"
NEGATIVE = "#D6455D"
NEUTRAL_TEXT = "#6B7280"

st.set_page_config(page_title="TEFAS Fon Takip Paneli", layout="wide")

st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
    html, body, [class*="css"] {
        font-family: "Inter", "Noto Sans", Arial, sans-serif;
    }
    h1 { font-size: 1.9rem !important; }
    h3 { font-size: 1.25rem !important; }
    p, li, .stMarkdown, .stCaption { font-size: 0.95rem !important; }
    div[data-testid="stTable"] table {
        border-collapse: collapse !important;
        width: 100%;
    }
    div[data-testid="stTable"] table td,
    div[data-testid="stTable"] table th,
    div[data-testid="stTable"] table td p,
    div[data-testid="stTable"] table th p {
        white-space: nowrap !important;
        font-size: 1.05rem !important;
        padding: 0.2rem 0.45rem !important;
    }
    div[data-testid="stTable"] table td,
    div[data-testid="stTable"] table th {
        border: 1.5px solid rgba(128, 128, 128, 0.55) !important;
    }
    div[data-testid="stTable"] table th {
        font-weight: 600 !important;
    }
    /* Fon Adı is the 2nd column in the returns table only — scoped via
       the table's own container key so it doesn't affect other tables.
       Truncated with an ellipsis instead of wrapping/overflowing, so no
       horizontal scrollbar shows up under the table. */
    div[class*="st-key-summary_table"] table td:nth-child(2),
    div[class*="st-key-summary_table"] table td:nth-child(2) p {
        font-size: 0.85rem !important;
        font-weight: 400 !important;
        max-width: 320px;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    /* Each returns-table cell is wrapped in a full-cell <a> (see
       _row_link in app.py) so the whole row is clickable. Move the
       cell padding onto the link itself so the clickable area covers
       the entire cell, not just the text, and add a hover cue. */
    div[class*="st-key-summary_table"] table td {
        padding: 0 !important;
    }
    div[class*="st-key-summary_table"] table td > a {
        display: block !important;
        padding: 0.2rem 0.45rem !important;
    }
    div[class*="st-key-summary_table"] table td:nth-child(2) > a {
        max-width: 320px;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }
    div[class*="st-key-summary_table"] table tbody tr:hover td {
        background-color: rgba(128, 128, 128, 0.15) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def sortable_header_row(col_defs: list, state_prefix: str) -> tuple:
    """Render a row of header buttons above a table (col_defs: list of
    (label, width_ratio, sortable)). Clicking a sortable header sets it as
    the sort column, toggling asc/desc on repeat clicks — same idea as
    clicking a column header in an interactive grid, but on a plain static
    table. Returns (sort_column_or_None, ascending).

    Note: st.columns widths are independent of the actual <table>'s
    browser-rendered column widths (which vary with cell content), so
    buttons won't line up pixel-perfectly with the columns below them.
    """
    col_key = f"{state_prefix}_sort_col"
    asc_key = f"{state_prefix}_sort_asc"
    cols = st.columns([w for _, w, _ in col_defs])
    for (label, _, sortable), c in zip(col_defs, cols):
        with c:
            if not sortable:
                st.markdown(f"**{label}**")
                continue
            current = st.session_state.get(col_key)
            asc = st.session_state.get(asc_key, False)
            arrow = (" ▲" if asc else " ▼") if current == label else " ⇅"
            if st.button(f"{label}{arrow}", key=f"{state_prefix}_hdr_{label}", use_container_width=True):
                if current == label:
                    st.session_state[asc_key] = not asc
                else:
                    st.session_state[col_key] = label
                    st.session_state[asc_key] = False
                st.rerun()
    return st.session_state.get(col_key), st.session_state.get(asc_key, False)


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
    """Format a fraction (0.05 -> +5.0000%)."""
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.4f}%"


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


if "group_name" not in st.session_state:
    st.session_state.group_name = next(iter(FUND_GROUPS))

with st.sidebar:
    st.caption("Fon Grubu")
    for name in FUND_GROUPS:
        is_active = st.session_state.group_name == name
        if st.button(
            name,
            key=f"group_btn_{name}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.group_name = name
            st.rerun()
    group_name = st.session_state.group_name
    st.markdown("---")
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

selected = FUND_GROUPS[group_name]

st.title("TEFAS Fon Takip Paneli")
st.caption(
    f"**{group_name}** grubu · Günlük ve haftalık getiriler fiyat "
    "geçmişinden hesaplanır; YTD TEFAS'ın kendi resmi karşılaştırma "
    "verisidir."
)

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
summary_col_defs = [
    ("Kod", 0.7, False),
    ("Fon Adı", 3.2, False),
    ("Son Fiyat", 1.0, False),
    ("Büyüklük", 1.3, True),
    ("Günlük", 0.9, True),
    ("Haftalık", 0.9, True),
    ("YTD", 0.9, True),
]
sort_col, sort_asc = sortable_header_row(summary_col_defs, "summary")
if sort_col:
    summary = summary.sort_values(sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

colored_cols = ["Günlük", "Haftalık", "YTD"]
numeric_cols = ["Son Fiyat", "Büyüklük", "Günlük", "Haftalık", "YTD"]


def _row_link(text: str, url: str) -> str:
    """Wrap cell text in a full-cell <a> so the whole row is clickable,
    while looking like plain text (no underline/blue, cursor still
    becomes a pointer on hover since it's a real anchor)."""
    return (
        f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
        f'style="display:block; color:inherit; text-decoration:none;">{text}</a>'
    )


linked_rows = []
for _, row in summary.iterrows():
    url = fund_detail_url(row["Kod"])
    linked_rows.append(
        {
            "Kod": _row_link(row["Kod"], url),
            "Fon Adı": _row_link(row["Fon Adı"], url),
            "Son Fiyat": _row_link(
                f"{row['Son Fiyat']:.6f}" if pd.notna(row["Son Fiyat"]) else "—", url
            ),
            "Büyüklük": _row_link(fmt_size(row["Büyüklük"]), url),
            "Günlük": _row_link(pct(row["Günlük"]), url),
            "Haftalık": _row_link(pct(row["Haftalık"]), url),
            "YTD": _row_link(pct(row["YTD"]), url),
        }
    )
linked_df = pd.DataFrame(linked_rows)

# Cell text is pre-formatted above (not via Styler.format) because the link
# wrapper needs the whole row's Kod to build each cell's href; Styler.format
# only sees one column at a time. Coloring still reads the original numeric
# `summary` values, so it stays correct regardless of the HTML wrapper.
styled_summary = linked_df.style.apply(
    lambda s: [f"color: {color_for(v)}" for v in summary[s.name]] if s.name in colored_cols else [""] * len(s),
    axis=0,
).set_properties(
    subset=numeric_cols, **{"font-weight": "bold"}
).hide(axis="index").hide(axis="columns")
# Static table: fixed column widths, no drag-to-resize, no column menu.
# Header is the button row above, not the table's own header. Keyed
# container so the Fon Adı font-size override (CSS above) only hits this
# table's 2nd column, not other tables. Every cell is a full-size <a> link
# (see _row_link) so clicking anywhere on a row opens that fund's TEFAS
# page in a new tab, while still displaying plain fund-code text.
with st.container(key="summary_table"):
    st.table(styled_summary)
st.caption(
    "Kod sütunundaki fon koduna tıklayarak ilgili fonun TEFAS sayfasını "
    "yeni sekmede açabilirsiniz. Büyüklük, TEFAS'ın güncel Fon Toplam "
    "Değer verisidir (TL). YTD sütunu TEFAS'ın kendi resmi getiri "
    "hesaplamasıdır. Günlük ve Haftalık, fiyat geçmişinden ayrıca "
    "hesaplanır."
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
    flow_col_defs = [("Kod", 0.7, False)] + [(c, 1.0, True) for c in flow_cols]
    flow_sort_col, flow_sort_asc = sortable_header_row(flow_col_defs, "flow")
    if flow_sort_col:
        flow_df = flow_df.sort_values(flow_sort_col, ascending=flow_sort_asc, na_position="last").reset_index(drop=True)
    styled_flows = flow_df.style.format({col: fmt_flow for col in flow_cols}).apply(
        lambda s: [f"color: {color_for(v)}" for v in flow_df[s.name]] if s.name in flow_cols else [""] * len(s),
        axis=0,
    ).set_properties(
        subset=flow_cols, **{"font-weight": "bold"}
    ).hide(axis="index").hide(axis="columns")
    # Static table: fixed column widths, no drag-to-resize, no column menu.
    # Header is the button row above, not the table's own header.
    st.table(styled_flows)
    if flow_df[flow_cols].isna().all(axis=None):
        st.caption("Para giriş/çıkışı şu an TEFAS'tan okunamadı; tabloda '—' olarak görünür.")

st.caption(f"Son güncelleme kontrolü: {date.today().isoformat()} · Kaynak: tefas.gov.tr")
