from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Preflight demo: invoice API")

# In-memory store for Phase 0; Postgres arrives in a later phase.
INVOICES: dict[str, dict] = {}


class Line(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    vat_rate: Decimal = Field(ge=0, le=1, description="e.g. 0.19 for 19%")


class InvoiceIn(BaseModel):
    customer_tax_id: str = Field(min_length=1)
    issue_date: date
    lines: list[Line] = Field(min_length=1)


class InvoiceOut(InvoiceIn):
    id: str
    total_excl_vat: Decimal
    total_vat: Decimal
    total_incl_vat: Decimal


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/invoices", status_code=201, response_model=InvoiceOut)
def create_invoice(invoice: InvoiceIn):
    excl = sum((l.quantity * l.unit_price for l in invoice.lines), Decimal(0))
    vat = sum((l.quantity * l.unit_price * l.vat_rate for l in invoice.lines), Decimal(0))
    cent = Decimal("0.001")  # TND has 3 decimals
    out = InvoiceOut(
        id=str(uuid4()),
        total_excl_vat=excl.quantize(cent),
        total_vat=vat.quantize(cent),
        total_incl_vat=(excl + vat).quantize(cent),
        **invoice.model_dump(),
    )
    INVOICES[out.id] = out.model_dump()
    return out


@app.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: str):
    if invoice_id not in INVOICES:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return INVOICES[invoice_id]
