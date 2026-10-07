"""Mock ERP: source of truth for customer master data.

Uses SAP-style field names (KUNNR, NAME1, ORT01, REGIO...) to mirror a typical
ERP customer master. Exposes a paginated, delta-capable REST API.
"""
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

API_KEY = "erp-demo-key"
app = FastAPI(title="Mock ERP - Customer Master")
DB: dict[str, dict] = {}


class Customer(BaseModel):
    KUNNR: str            # customer number
    NAME1: str            # name
    ORT01: str            # city
    REGIO: str            # region / state code
    LAND1: str = "IN"     # country
    SMTP_ADDR: str = ""   # email
    TELF1: str = ""       # phone
    KLIMK: float = 0      # credit limit
    SPERR: bool = False   # posting block
    CHANGED_AT: str = ""


def auth(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(401, "invalid API key")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@app.get("/api/v1/customers", dependencies=[Depends(auth)])
def list_customers(changed_since: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, le=200)):
    rows = sorted((c for c in DB.values() if c["CHANGED_AT"] > changed_since), key=lambda c: c["CHANGED_AT"])
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "page": page,
            "has_more": start + page_size < len(rows), "total": len(rows)}


@app.put("/api/v1/customers/{kunnr}", dependencies=[Depends(auth)])
def upsert_customer(kunnr: str, c: Customer):
    rec = c.model_dump() | {"KUNNR": kunnr, "CHANGED_AT": now()}
    DB[kunnr] = rec
    return rec


@app.get("/api/v1/customers/{kunnr}", dependencies=[Depends(auth)])
def get_customer(kunnr: str):
    if kunnr not in DB:
        raise HTTPException(404, "not found")
    return DB[kunnr]
