from app.main import app


def test_customer_and_supplier_statement_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/statements/{counterparty_type}/{counterparty_id}" in paths
    operation = app.openapi()["paths"][
        "/api/v1/accounting/statements/{counterparty_type}/{counterparty_id}"
    ]["get"]
    names = {item["name"] for item in operation["parameters"]}
    assert {"counterparty_type", "counterparty_id", "start_date", "end_date"} <= names
