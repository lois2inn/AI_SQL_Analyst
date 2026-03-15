""" Sales Data Analysis Library

This module provides utilities for:
- Converting natural language requests to SQL queries using LLM
- Executing validated SELECT-only queries against a SQLite database
- Analyzing query results using LLM-powered insights

The module integrates with OpenRouter API for LLM capabilities and enforces
strict SQL validation to prevent destructive operations.
"""

import sqlite3
import os
import json
import pandas as pd 
import re

from dotenv import load_dotenv
from openai import OpenAI


DEFAULT_SCHEMA = """customers(customer_id, customer_name, city, state, country),
products(product_id, product_name, category),
orders(order_id, product_id, customer_id, unit_price, quantity, discount, order_date)"""


def get_openai_client():
    """Create and return an OpenAI client configured for OpenRouter.

    Loads environment variables from `.env` and reads `API_KEY`.

    Returns:
        OpenAI: Configured OpenAI client.

    Raises:
        ValueError: If `API_KEY` is missing.
    """
    load_dotenv()
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("Missing API_KEY in environment")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def validate_select_only_sql(sql_query: str):
    """Validate that a SQL string is a single-statement, read-only SELECT query.

    Enforces:
        - Single statement (only optional trailing semicolon)
        - Must start with `SELECT` or `WITH` (CTE)
        - Rejects common write/DDL/admin keywords

    Args:
        sql_query (str): SQL query to validate.

    Returns:
        str: Normalized SQL string with any trailing semicolon removed.

    Raises:
        ValueError: If the query is not a safe, single-statement SELECT.
    """
    if not isinstance(sql_query, str):
        raise ValueError("SQL query must be a string")

    q = sql_query.strip()
    if not q:
        raise ValueError("SQL query is empty")

    if "\x00" in q:
        raise ValueError("SQL query contains invalid characters")

    if q.count(";") > 1:
        raise ValueError("Only single-statement SELECT queries are allowed")
    if ";" in q and not q.rstrip().endswith(";"):
        raise ValueError("Only a trailing semicolon is allowed")

    q_no_trailing_semicolon = q[:-1].strip() if q.rstrip().endswith(";") else q
    lowered = q_no_trailing_semicolon.lstrip().lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT queries are allowed")
    if lowered.startswith("with") and " select " not in f" {lowered} ":
        raise ValueError("CTE query must contain a SELECT statement")

    forbidden = [
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "replace",
        "truncate",
        "attach",
        "detach",
        "pragma",
        "vacuum",
        "reindex",
        "analyze",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
    ]
    pattern = re.compile(r"\b(" + "|".join(forbidden) + r")\b", re.IGNORECASE)
    match = pattern.search(q_no_trailing_semicolon)
    if match:
        raise ValueError(f"Disallowed SQL keyword found: {match.group(1)}")

    return q_no_trailing_semicolon


def normalize_llm_sql_output(raw_text: str):
    """Normalize raw model output into executable SQL text.

    Strips markdown code fences and rejects any non-SQL prefix text.

    Args:
        raw_text (str): Raw model response text.

    Returns:
        str: Extracted SQL statement.

    Raises:
        ValueError: If the output is empty or contains non-SQL prefix text.
    """
    if raw_text is None:
        raise ValueError("Model returned empty SQL output")

    text = str(raw_text).strip()
    if not text:
        raise ValueError("Model returned empty SQL output")

    if "```" in text:
        lines = text.splitlines()
        in_fence = False
        fence_lines = []
        for line in lines:
            s = line.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                fence_lines.append(line)
        if fence_lines:
            text = "\n".join(fence_lines).strip()

    start_idx = None
    lowered = text.lower()
    for kw in ("select", "with"):
        idx = lowered.find(kw)
        if idx != -1:
            start_idx = idx if start_idx is None else min(start_idx, idx)
    if start_idx is None:
        raise ValueError("Model output did not contain a SQL SELECT statement")

    prefix = text[:start_idx].strip()
    if prefix:
        raise ValueError("Model output contained text before SQL; refusing to execute")

    sql = text[start_idx:].strip()
    if not sql:
        raise ValueError("Model returned empty SQL after normalization")

    return sql


def nl_to_sql(
    nl_request: str,
    schema: str = DEFAULT_SCHEMA,
    client: OpenAI | None = None,
    model: str = "openai/gpt-4.1-nano",
    max_tokens: int = 200,
):
    """Convert a natural-language request into a validated, SELECT-only SQLite query.

    Args:
        nl_request (str): User request in natural language.
        schema (str): Schema description to condition the model.
        client (OpenAI | None): Optional cached OpenAI client.
        model (str): Model identifier.
        max_tokens (int): Max tokens for SQL generation response.

    Returns:
        str: Validated SQL query string safe to execute.

    Raises:
        ValueError: If model output is not valid SELECT-only SQL.
    """
    if client is None:
        client = get_openai_client()
    prompt = (
        "Convert the user request into a single SQLite SQL query. "
        "Return ONLY the SQL query text (no markdown, no explanations).\n\n"
        f"Schema: {schema}\n\n"
        f"User request: {nl_request}"
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    raw_sql = completion.choices[0].message.content
    normalized = normalize_llm_sql_output(raw_sql)
    validated = validate_select_only_sql(normalized)
    return validated


def run_sql_query(
    sql_query: str,
    db_path: str = "sales.db",
):
    """Execute a validated SELECT-only SQL query against SQLite.

    Args:
        sql_query (str): SQL query to execute.
        db_path (str): Path to SQLite database.

    Returns:
        tuple[pd.DataFrame, str]: DataFrame of results and JSON-serialized rows.

    Raises:
        ValueError: If SQL fails SELECT-only validation.
    """
    sql_query = validate_select_only_sql(sql_query)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql_query, conn)
    finally:
        conn.close()
    rows = df.to_dict(orient="records")
    rows_json = json.dumps(rows, default=str)
    return df, rows_json


def analyze_rows_json(
    analysis_request: str,
    sql_query: str,
    rows_json: str,
    client: OpenAI | None = None,
    model: str = "openai/gpt-4.1-nano",
    max_tokens: int = 300,
):
    """Ask the model to analyze SQL query results represented as JSON rows.

    Args:
        analysis_request (str): Question/instruction for the analysis.
        sql_query (str): SQL used to produce the results.
        rows_json (str): JSON string of result rows.
        client (OpenAI | None): Optional cached OpenAI client.
        model (str): Model identifier.
        max_tokens (int): Max tokens for analysis response.

    Returns:
        str | None: Model-generated analysis text.
    """
    if client is None:
        client = get_openai_client()
    messages = [
        {
            "role": "user",
            "content": (
                "You are a data analyst. You are given SQL query results as JSON rows. "
                "Answer the analysis request using only the provided data.\n\n"
                f"Analysis request: {analysis_request}\n\n"
                f"SQL: {sql_query}\n\n"
                f"Rows (JSON): {rows_json}"
            ),
        }
    ]
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return completion.choices[0].message.content


def nl_request_to_analysis(
    nl_request: str,
    schema: str = DEFAULT_SCHEMA,
    client: OpenAI | None = None,
    sql_model: str = "openai/gpt-4.1-nano",
    analysis_model: str = "openai/gpt-4.1-nano",
    max_rows: int = 50,
):
    """Run the full pipeline: NL request -> SQL -> SQLite -> JSON -> LLM analysis.

    Args:
        nl_request (str): Natural-language request.
        schema (str): Schema description.
        client (OpenAI | None): Optional cached OpenAI client.
        sql_model (str): Model used for SQL generation.
        analysis_model (str): Model used for analysis.
        max_rows (int): Max result rows forwarded to analysis.

    Returns:
        tuple[str, pd.DataFrame, str, str | None]: SQL query, DataFrame, rows JSON, analysis.
    """
    sql_query = nl_to_sql(
        nl_request=nl_request,
        schema=schema,
        client=client,
        model=sql_model,
    )
    df, rows_json = run_sql_query(sql_query)
    if max_rows is not None and len(df) > max_rows:
        df = df.head(max_rows)
        rows_json = json.dumps(df.to_dict(orient="records"), default=str)
    analysis = analyze_rows_json(
        analysis_request=nl_request,
        sql_query=sql_query,
        rows_json=rows_json,
        client=client,
        model=analysis_model,
    )
    return sql_query, df, rows_json, analysis


def get_sales_data(sql_query):
    """
    Fetch sales data from the database based on the
    provided SQL query and return it as JSON.
    Args:
    sql_query (str): The SQL query to execute against the database.
    Returns:
    str: The sales data in JSON format.
        """
    sql_query = validate_select_only_sql(sql_query)
    conn = sqlite3.connect('sales.db')
    df = pd.read_sql_query(sql_query, conn)
    conn.close()
    return df.to_json()


def analyze_sales_data(
    sql_query: str,
    analysis_request: str,
    model: str = "openai/gpt-4.1-nano",
    max_rows: int = 20,
    max_tokens: int = 100,
):
    """Analyze results of an explicit SQL query using the LLM.

    This is a convenience wrapper around `run_sql_query` + `analyze_rows_json`.
    The SQL is validated to be SELECT-only before executing.

    Args:
        sql_query (str): SQL query to run.
        analysis_request (str): Analysis prompt.
        model (str): Model identifier.
        max_rows (int): Max number of rows included in the prompt.
        max_tokens (int): Max tokens for the analysis response.

    Returns:
        str | None: Model-generated analysis text.
    """
    df, rows_json = run_sql_query(sql_query)

    if max_rows is not None and len(df) > max_rows:
        df = df.head(max_rows)
        rows_json = json.dumps(df.to_dict(orient="records"), default=str)

    return analyze_rows_json(
        analysis_request=analysis_request,
        sql_query=sql_query,
        rows_json=rows_json,
        model=model,
        max_tokens=max_tokens,
    )


# the main entry point to this file
if __name__ == "__main__":
    sales_data = get_sales_data("SELECT * FROM orders LIMIT 1")
    print(sales_data)

    analysis = analyze_sales_data(
        sql_query="""SELECT 
    c.city, 
    COUNT(o.order_id) AS total_orders
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
GROUP BY c.city
ORDER BY total_orders DESC
LIMIT 5;""",
        analysis_request="Summarize total orders by city and identify any notable patterns.",
    )
    print(analysis)
