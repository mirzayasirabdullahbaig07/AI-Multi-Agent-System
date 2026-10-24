"""
tools.py
Everything the agents can *do* outside the LLM:

  * DATA_TOOLS   read-only queries over the SQLite business database (Analyst only)
  * SEARCH_TOOLS external web search via Tavily (Research Agent only)

Each agent receives only its own registry, and BaseAgent refuses any other
tool name, so roles are enforced by code and not just by the prompt.

The business dataset is the same synthetic dataset used in Week 8 (same seed),
including one engineered pattern: UrbanTote Backpack's June price cut with a
flat order count. Run `python -m src.tools` to (re)build it.
"""

import csv
import random
import sqlite3
from datetime import date, timedelta
from typing import List, Optional

import requests

from . import config

# =============================================================================
# Synthetic business dataset (identical generator and seed to Week 8)
# =============================================================================
REGION_WEIGHTS = [0.42, 0.30, 0.18, 0.10]
SEGMENTS = ["Retail", "Wholesale"]
SEGMENT_WEIGHTS = [0.75, 0.25]

PRODUCTS = [
    (1, "UrbanTote Backpack", "Apparel", 3500),
    (2, "AeroFit Running Shoes", "Apparel", 4200),
    (3, "PixelBeam LED Lamp", "Home", 1800),
    (4, "CrispAir Fan", "Home", 5200),
    (5, "SonicPods Earbuds", "Electronics", 6500),
    (6, "VoltCharge Power Bank", "Electronics", 2200),
    (7, "GlowSkin Face Serum", "Beauty", 1500),
    (8, "PureMist Diffuser", "Home", 2600),
    (9, "TrailBlaze Water Bottle", "Apparel", 900),
    (10, "NovaView Sunglasses", "Apparel", 1700),
]

MONTHS = [(2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6)]
ANOMALY_PRODUCT_ID = 1
ANOMALY_MONTH = (2026, 6)
ANOMALY_DISCOUNT = 0.68

FIRST_NAMES = ["Ayesha", "Bilal", "Sara", "Omar", "Zainab", "Hamza", "Fatima", "Ali",
               "Mehwish", "Usman", "Noor", "Hassan", "Amna", "Saad", "Maryam", "Tariq"]
LAST_NAMES = ["Khan", "Malik", "Siddiqui", "Raza", "Qureshi", "Butt", "Shaikh", "Chaudhry"]


def _month_dates(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, (end - start).days


def _generate_customers(rng: random.Random, n: int = 60):
    rows = []
    start_pool = date(2025, 6, 1)
    for cid in range(1, n + 1):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        region = rng.choices(config.REGIONS, weights=REGION_WEIGHTS)[0]
        segment = rng.choices(SEGMENTS, weights=SEGMENT_WEIGHTS)[0]
        signup = start_pool + timedelta(days=rng.randint(0, 400))
        rows.append((cid, name, region, segment, signup.isoformat()))
    return rows


def _generate_orders_and_sales(rng: random.Random, customers):
    orders, sales = [], []
    order_id = sale_id = 1
    customer_ids = [c[0] for c in customers]
    customer_region = {c[0]: c[2] for c in customers}

    for (year, month) in MONTHS:
        start, days = _month_dates(year, month)
        for _ in range(rng.randint(78, 92)):
            cust_id = rng.choice(customer_ids)
            order_date = start + timedelta(days=rng.randint(0, days - 1))
            orders.append((order_id, cust_id, order_date.isoformat(), customer_region[cust_id]))

            n_items = rng.choices([1, 2, 3], weights=[0.55, 0.35, 0.10])[0]
            for pid, _name, _cat, base_price in rng.sample(PRODUCTS, k=min(n_items, len(PRODUCTS))):
                quantity = rng.randint(1, 4)
                unit_price = base_price * rng.uniform(0.95, 1.05)
                if pid == ANOMALY_PRODUCT_ID and (year, month) == ANOMALY_MONTH:
                    unit_price = base_price * ANOMALY_DISCOUNT * rng.uniform(0.97, 1.03)
                unit_price = round(unit_price, 2)
                sales.append((sale_id, order_id, pid, quantity, unit_price, round(unit_price * quantity, 2)))
                sale_id += 1
            order_id += 1
    return orders, sales


def _write_csvs() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    customers = _generate_customers(rng)
    orders, sales = _generate_orders_and_sales(rng, customers)

    def write(path, header, rows):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    write(config.CUSTOMERS_CSV, ["customer_id", "name", "region", "segment", "signup_date"], customers)
    write(config.PRODUCTS_CSV, ["product_id", "name", "category", "base_price"], PRODUCTS)
    write(config.ORDERS_CSV, ["order_id", "customer_id", "order_date", "region"], orders)
    write(config.SALES_CSV, ["sale_id", "order_id", "product_id", "quantity", "unit_price", "revenue"], sales)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
    region TEXT NOT NULL, segment TEXT NOT NULL, signup_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products (product_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
    category TEXT NOT NULL, base_price REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders (order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL, region TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales (sale_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL, unit_price REAL NOT NULL, revenue REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id);
CREATE INDEX IF NOT EXISTS idx_sales_order ON sales(order_id);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_database(force: bool = False) -> None:
    """Build data/business.db from the CSVs (generating the CSVs first if missing). Safe to call repeatedly."""
    if force or not config.CUSTOMERS_CSV.exists():
        _write_csvs()
    if config.DB_PATH.exists() and not force:
        return
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()

    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        for path, table, n_cols in ((config.CUSTOMERS_CSV, "customers", 5), (config.PRODUCTS_CSV, "products", 4),
                                    (config.ORDERS_CSV, "orders", 4), (config.SALES_CSV, "sales", 6)):
            with open(path) as f:
                reader = csv.reader(f)
                next(reader)
                placeholders = ",".join("?" * n_cols)
                conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", reader)
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# DATA_TOOLS: read-only business queries (Analyst only)
# =============================================================================
def _rows(rows) -> List[dict]:
    return [dict(r) for r in rows]


def list_available_months() -> List[str]:
    conn = get_connection()
    try:
        return [r["month"] for r in conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', order_date) AS month FROM orders ORDER BY month")]
    finally:
        conn.close()


def get_product_names() -> List[str]:
    conn = get_connection()
    try:
        return [r["name"] for r in conn.execute("SELECT name FROM products ORDER BY product_id")]
    finally:
        conn.close()


def get_regional_trend(months: int = 6) -> List[dict]:
    """Revenue and order count by region, month by month (last `months` per region)."""
    conn = get_connection()
    try:
        rows = _rows(conn.execute("""
            SELECT strftime('%Y-%m', o.order_date) AS month, o.region AS region,
                   SUM(s.revenue) AS revenue, COUNT(DISTINCT o.order_id) AS orders
            FROM sales s JOIN orders o ON s.order_id = o.order_id
            GROUP BY month, region ORDER BY region, month"""))
    finally:
        conn.close()
    by_region: dict = {}
    for row in rows:
        by_region.setdefault(row["region"], []).append(row)
    return [r for region_rows in by_region.values() for r in region_rows[-months:]] if months else rows


def get_product_sales(product_name: Optional[str] = None, months: int = 6) -> List[dict]:
    """Month-by-month revenue, units, orders and average unit price per product (last `months`)."""
    conn = get_connection()
    try:
        query = """
            SELECT strftime('%Y-%m', o.order_date) AS month, p.name AS product,
                   SUM(s.revenue) AS revenue, SUM(s.quantity) AS units,
                   COUNT(DISTINCT o.order_id) AS orders, ROUND(AVG(s.unit_price), 2) AS avg_unit_price
            FROM sales s JOIN orders o ON s.order_id = o.order_id JOIN products p ON s.product_id = p.product_id
            WHERE 1=1"""
        params: list = []
        if product_name:
            query += " AND p.name LIKE ?"
            params.append(f"%{product_name}%")
        query += " GROUP BY month, p.name ORDER BY product, month"
        rows = _rows(conn.execute(query, params))
    finally:
        conn.close()
    by_product: dict = {}
    for row in rows:
        by_product.setdefault(row["product"], []).append(row)
    return [r for product_rows in by_product.values() for r in product_rows[-months:]] if months else rows


def get_top_products(month: Optional[str] = None, limit: int = 5) -> List[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT p.name AS product, p.category AS category, SUM(s.revenue) AS revenue, SUM(s.quantity) AS units
            FROM sales s JOIN products p ON s.product_id = p.product_id JOIN orders o ON s.order_id = o.order_id
            WHERE 1=1"""
        params: list = []
        if month:
            query += " AND strftime('%Y-%m', o.order_date) = ?"
            params.append(month)
        query += " GROUP BY p.name, p.category ORDER BY revenue DESC LIMIT ?"
        params.append(limit)
        return _rows(conn.execute(query, params))
    finally:
        conn.close()


def get_customer_metrics(month: Optional[str] = None) -> List[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT c.segment AS segment, COUNT(DISTINCT o.order_id) AS orders, SUM(s.revenue) AS revenue,
                   ROUND(SUM(s.revenue) * 1.0 / COUNT(DISTINCT o.order_id), 2) AS avg_order_value
            FROM sales s JOIN orders o ON s.order_id = o.order_id JOIN customers c ON o.customer_id = c.customer_id
            WHERE 1=1"""
        params: list = []
        if month:
            query += " AND strftime('%Y-%m', o.order_date) = ?"
            params.append(month)
        query += " GROUP BY c.segment ORDER BY revenue DESC"
        return _rows(conn.execute(query, params))
    finally:
        conn.close()


DATA_TOOLS = {
    "list_available_months": list_available_months,
    "get_product_names": get_product_names,
    "get_regional_trend": get_regional_trend,
    "get_product_sales": get_product_sales,
    "get_top_products": get_top_products,
    "get_customer_metrics": get_customer_metrics,
}


# =============================================================================
# SEARCH_TOOLS: external research (Research Agent only)
# =============================================================================
TAVILY_ENDPOINT = "https://api.tavily.com/search"


class ResearchUnavailable(Exception):
    """Raised when external search cannot be used. A normal, handled outcome, not a crash."""


def search_external_information(query: str, max_results: int = 3) -> List[dict]:
    """Return [{title, url, snippet}] from Tavily. Raises ResearchUnavailable if no key is set or the call fails.

    The key is sent as a Bearer header; it is also included in the body for older API versions.
    (Not yet tested against the live API: needs a TAVILY_API_KEY.)
    """
    key = config.TAVILY_API_KEY
    if not key:
        raise ResearchUnavailable("External research is not configured (no TAVILY_API_KEY set).")
    try:
        response = requests.post(
            TAVILY_ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            json={"api_key": key, "query": query, "max_results": max_results, "search_depth": "basic"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        raise ResearchUnavailable(f"External research request failed: {e}") from e

    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])[:max_results] if r.get("url")]


SEARCH_TOOLS = {"search_external_information": search_external_information}


if __name__ == "__main__":
    build_database(force=True)
    conn = get_connection()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("customers", "products", "orders", "sales")}
    conn.close()
    print("Database built at", config.DB_PATH)
    print(counts)
