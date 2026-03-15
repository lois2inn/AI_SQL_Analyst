"""
Code to interact with OpenAI API using Python.
This code loads the API key from an environment variable
and initializes the OpenAI client.
"""

import streamlit as st

import pandas as pd
import warnings

from sales_data import DEFAULT_SCHEMA, analyze_rows_json, get_openai_client, nl_to_sql, run_sql_query


st.set_page_config(page_title="Sales Data Analyst", layout="centered")

st.title("Sales Data Analyst")


@st.cache_resource
def cached_openai_client():
    """Return a cached OpenAI client for reuse across Streamlit reruns."""
    return get_openai_client()


@st.cache_data
def cached_sql_results(sql_query: str):
    """Return cached (DataFrame, JSON rows) for a given validated SQL query."""
    return run_sql_query(sql_query)


def _pick_value_column(df: pd.DataFrame):
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return None

    preferred_names = {
        "value",
        "total",
        "total_orders",
        "total_sales",
        "sales",
        "revenue",
        "amount",
        "count",
        "qty",
        "quantity",
    }
    for c in numeric_cols:
        if c.lower() in preferred_names:
            return c

    if len(numeric_cols) == 1:
        return numeric_cols[0]
    return numeric_cols[0]


def _pick_date_column(df: pd.DataFrame):
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c

    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]):
            parsed = pd.to_datetime(df[c], errors="coerce", format="ISO8601")
            if parsed.notna().mean() < 0.8:
                try:
                    parsed = pd.to_datetime(df[c], errors="coerce", format="mixed")
                except TypeError:
                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore",
                            message="Could not infer format, so each element will be parsed individually*",
                            category=UserWarning,
                        )
                        parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                df[c] = parsed
                return c
    return None


def _pick_category_column(df: pd.DataFrame, exclude_cols: set[str]):
    for c in df.columns:
        if c in exclude_cols:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            continue
        return c
    return None


def render_auto_chart(df: pd.DataFrame):
    if df is None or df.empty:
        return

    value_col = _pick_value_column(df)
    if value_col is None:
        return

    date_col = _pick_date_column(df)
    if date_col is not None and date_col != value_col:
        plot_df = df[[date_col, value_col]].dropna().sort_values(date_col)
        if not plot_df.empty:
            st.subheader("Visualization")
            st.line_chart(plot_df.set_index(date_col)[value_col])
        return

    category_col = _pick_category_column(df, exclude_cols={value_col})
    if category_col is not None:
        plot_df = df[[category_col, value_col]].dropna().sort_values(value_col, ascending=False)
        if not plot_df.empty:
            st.subheader("Visualization")
            st.bar_chart(plot_df.set_index(category_col)[value_col])
        return

SAMPLE_QUESTIONS = {
    "Top products by revenue": "List the top 5 products by total revenue.",
    "Revenue by city": "Show total revenue by city, sorted descending.",
    "Monthly sales trends": "Show monthly total revenue over time.",
    "Top customers by spending": "List the top 5 customers by total spending.",
}

if "nl_request" not in st.session_state:
    st.session_state["nl_request"] = "What are the top 3 cities with the most orders?"

sample_choice = st.selectbox(
    "Sample business questions",
    options=["(choose one)"] + list(SAMPLE_QUESTIONS.keys()),
    index=0,
)

apply_sample = st.button("Use sample", disabled=(sample_choice == "(choose one)"))
if apply_sample:
    st.session_state["nl_request"] = SAMPLE_QUESTIONS[sample_choice]

nl_request = st.text_area(
    "Request",
    key="nl_request",
    height=100,
)

schema_tab, erd_tab = st.tabs(["Schema", "ERD"])

with schema_tab:
    st.code(DEFAULT_SCHEMA)

with erd_tab:
    st.image("sales_erd.png", width="stretch")

run = st.button("Run", type="primary")

if run:
    try:
        with st.spinner("Generating SQL, querying SQLite, and analyzing results..."):
            client = cached_openai_client()
            sql_query = nl_to_sql(nl_request=nl_request, client=client)
            df, rows_json = cached_sql_results(sql_query)
            analysis = analyze_rows_json(
                analysis_request=nl_request,
                sql_query=sql_query,
                rows_json=rows_json,
                client=client,
            )

        st.subheader("Generated SQL")
        st.code(sql_query, language="sql")

        st.subheader("Query Results")
        st.dataframe(df, width="stretch")

        render_auto_chart(df)

        st.subheader("Analysis Results")
        st.write(analysis)
    except Exception as e:
        st.error(str(e))
