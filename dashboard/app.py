"""Streamlit dashboard: pick a procedure, see the price spread by hospital and payer, with quality score visible.
Queries the same db.py layer as the API (not a second data path) -- reads the local DuckDB gold DB directly."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pricecheck.serving import db  # noqa: E402
from pricecheck.serving.constants import DISCLAIMER  # noqa: E402

st.set_page_config(page_title="Price Check", layout="wide")
st.title("Price Check")
st.caption(DISCLAIMER)

col1, col2 = st.columns([2, 1])
with col1:
    q = st.text_input("Search for a procedure", value="MRI")
with col2:
    limit = st.slider("Results", 5, 50, 15)

if q and len(q) >= 2:
    hits = db.search_procedures(q, limit)
    if not hits:
        st.warning("No matches.")
    else:
        df = pd.DataFrame(hits)
        picked = st.selectbox("Pick a code", df.code + " (" + df.code_type + ") -- " + df.example_description.fillna(""))
        code = picked.split(" ")[0]

        rows = db.price_spread(code)
        if not rows:
            st.warning("No price data for that code.")
        else:
            spread = pd.DataFrame(rows)
            st.subheader(f"{code} -- {spread.example_description.iloc[0] or ''}")
            for _, r in spread.iterrows():
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric(f"{r.price_type} min", f"${r.min_amount:,.2f}")
                c2.metric(f"{r.price_type} median", f"${r.median_amount:,.2f}")
                c3.metric(f"{r.price_type} max", f"${r.max_amount:,.2f}")
                c4.metric("hospitals", int(r.n_hospitals))
                c5.metric("flagged", f"{int(r.n_flagged)} ({r.pct_flagged}%)")
            st.dataframe(spread, use_container_width=True)

st.divider()
st.subheader("Hospital data quality")
st.caption("Completeness, validity, consistency, freshness -- see DECISIONS.md ADR-014 for exactly how each is computed.")
q_df = pd.DataFrame(db.hospital_quality())
st.dataframe(
    q_df[["hospital_slug", "hospital_name", "state", "quality_score", "quality_band", "pct_flagged", "days_since_last_update"]]
    .sort_values("quality_score", ascending=False),
    use_container_width=True, hide_index=True,
)
st.bar_chart(q_df.set_index("hospital_slug")["quality_score"].sort_values(ascending=False))
