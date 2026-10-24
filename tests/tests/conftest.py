import pytest

from src import config, tools


@pytest.fixture(scope="session", autouse=True)
def business_db(tmp_path_factory):
    """Build the sample business database in a temp folder, so tests never touch the real data/ folder."""
    tmp = tmp_path_factory.mktemp("data")
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "DATA_DIR", tmp)
    mp.setattr(config, "DB_PATH", tmp / "business.db")
    mp.setattr(config, "CUSTOMERS_CSV", tmp / "customers.csv")
    mp.setattr(config, "PRODUCTS_CSV", tmp / "products.csv")
    mp.setattr(config, "ORDERS_CSV", tmp / "orders.csv")
    mp.setattr(config, "SALES_CSV", tmp / "sales.csv")
    tools.build_database(force=True)
    yield tmp
    mp.undo()
