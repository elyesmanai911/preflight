from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

INVOICE = {
    "customer_tax_id": "1234567A",
    "issue_date": "2026-11-12",
    "lines": [
        {
            "description": "Consulting",
            "quantity": "2",
            "unit_price": "100",
            "vat_rate": "0.19",
        },
        {
            "description": "Licence",
            "quantity": "1",
            "unit_price": "50.5",
            "vat_rate": "0.07",
        },
    ],
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_fetch_invoice():
    r = client.post("/invoices", json=INVOICE)
    assert r.status_code == 201
    body = r.json()
    assert body["total_excl_vat"] == "250.500"
    assert body["total_vat"] == "41.535"  # 200*0.19 + 50.5*0.07
    assert body["total_incl_vat"] == "292.035"
    assert body["flagged"] is False

    r = client.get(f"/invoices/{body['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == body["id"]


def test_flags_invoice_with_nonexistent_vat_rate():
    bad_line = {**INVOICE["lines"][0], "vat_rate": "0.18"}  # 18% is not a Tunisian rate
    r = client.post("/invoices", json={**INVOICE, "lines": [bad_line]})
    assert r.status_code == 201
    assert r.json()["flagged"] is True
    assert r.json()["anomaly_score"] >= 0.5


def test_rejects_invoice_without_lines():
    r = client.post("/invoices", json={**INVOICE, "lines": []})
    assert r.status_code == 422


def test_rejects_negative_quantity():
    bad_line = {**INVOICE["lines"][0], "quantity": "-1"}
    r = client.post("/invoices", json={**INVOICE, "lines": [bad_line]})
    assert r.status_code == 422


def test_unknown_invoice_returns_404():
    assert client.get("/invoices/nope").status_code == 404
