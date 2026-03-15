# Sales Data Analyst (Streamlit + SQLite + LLM)
A lightweight analytics app that lets you ask business questions in plain English and get:

- Generated SQL (SELECT-only)
- Query results from a local SQLite database (`sales.db`)
- LLM-generated analysis and an auto chart (bar/line) when the result shape supports it

The app uses OpenRouter (OpenAI-compatible API) to:

1. Convert a natural-language question into a SQLite `SELECT` query
2. Analyze the resulting rows for patterns/insights

## Overview
This project demonstrates an end-to-end pattern for “conversational analytics” on top of a relational database:

- **User** types a business question (e.g., “Top products by revenue”)
- **LLM** generates a **validated** SQL query
- **SQLite** executes the query and returns a DataFrame
- **LLM** produces a narrative analysis based on the returned rows
- **Streamlit** displays the SQL, the results table, and a visualization (when applicable)

## Architecture

### High-level components

- **`app.py`**
  - Streamlit UI
  - Caching:
    - `st.cache_resource` for the OpenAI client
    - `st.cache_data` for SQL query results
  - Renders:
    - Generated SQL
    - Results table
    - Automatic visualization
    - LLM analysis response

- **`sales_data.py`**
  - Backend functions:
    - `nl_to_sql(...)`: Natural language -> SQL via LLM (normalized + validated)
    - `validate_select_only_sql(...)`: Enforces SELECT-only, single statement guardrails
    - `run_sql_query(...)`: Executes validated SQL on SQLite and returns `(df, rows_json)`
    - `analyze_rows_json(...)`: Sends JSON rows back to LLM for insights
  - Optional orchestration helper:
    - `nl_request_to_analysis(...)`

- **`sales.db`**
  - SQLite database storing the star-schema style tables (`customers`, `orders`, `products`)

- **`sales_erd.png`**
  - Entity Relationship Diagram shown in the UI

### Data flow

1. User enters a request in Streamlit
2. `nl_to_sql()` calls the model to generate SQL
3. SQL output is normalized (`normalize_llm_sql_output`) and validated (`validate_select_only_sql`)
4. `run_sql_query()` executes the SQL against `sales.db` and returns:
   - a pandas `DataFrame`
   - JSON rows (for LLM analysis)
5. `analyze_rows_json()` sends JSON rows to the model for pattern analysis
6. Streamlit renders results + chart:
   - Bar chart for *(category, value)*
   - Line chart for *(date, value)*

## SQL safety guardrails

To prevent unsafe statements, the backend enforces:

- Only **single-statement** queries
- Query must begin with `SELECT` or `WITH ... SELECT ...`
- Rejects common write/DDL/admin keywords (e.g., `INSERT`, `UPDATE`, `DELETE`, `DROP`, `PRAGMA`, etc.)

If the LLM returns any extra prose or non-SQL prefixes, it is rejected.


## Technologies used

- **Python**
- **Streamlit** (UI)
- **SQLite** (database)
- **pandas** (DataFrame handling)
- **OpenAI Python SDK** (OpenAI-compatible client)
- **OpenRouter** (API gateway / model provider)
- **pytest** (unit tests)


## Setup

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure environment variables

Create a `.env` file in the project root:

```bash
API_KEY="<your-openrouter-api-key>"
```

### 3) Run the Streamlit app

```bash
streamlit run app.py
```
## Usage

- Pick a sample question (optional) and click **Use sample**, or type your own.
- Click **Run**.
- Review:
  - Generated SQL
  - Query results
  - Visualization (when detected)
  - Analysis response

## Notes

- This project expects a local `sales.db` in the project root.
- For large result sets, consider adding aggregation in SQL (GROUP BY) to keep prompts small.
- Do not commit secrets: add `.env` to `.gitignore` before publishing.

## Potential enhancements:
-   Schema auto-discovery
-   Multi-step AI agents
-   Support for multiple databases

## License
MIT License


