"""Mock CRM: target system holding customer accounts.

Accounts are keyed by the CRM's own id and carry the ERP number as `external_id`.
Set `FAILURES['remaining']` to simulate transient 503s for retry testing.
"""
import itertools
import re
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator

TOKEN = "crm-demo-token"
app = FastAPI(title="Mock CRM - Accounts")
DB: dict[str, dict] = {}
_ids = itertools.count(1)
FAILURES = {"remaining": 0}


class Account(BaseModel):
    external_id: str
    account_name: str
    billing_city: str
    billing_state: str
    billing_country: str
    email: str | None = None
    phone: str | None = None
    credit_limit: float = 0
    status: str = "Active"

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", v, re.I):
            raise ValueError("invalid email")
        return v or None

    @field_validator("status")
    @classmethod
    def check_status(cls, v):
        if v not in {"Active", "On Hold"}:
            raise ValueError("status must be Active or On Hold")
        return v


def auth(authorization: str = Header(default="")):
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "invalid token")
    if FAILURES["remaining"] > 0:
        FAILURES["remaining"] -= 1
        raise HTTPException(503, "temporarily unavailable")


@app.get("/accounts", dependencies=[Depends(auth)])
def find(external_id: str):
    hit = [a for a in DB.values() if a["external_id"] == external_id]
    return {"items": hit}


@app.post("/accounts", status_code=201, dependencies=[Depends(auth)])
def create(a: Account):
    if any(x["external_id"] == a.external_id for x in DB.values()):
        raise HTTPException(409, "external_id already exists")
    rec = {"id": f"ACC-{next(_ids):05d}", **a.model_dump()}
    DB[rec["id"]] = rec
    return rec


@app.patch("/accounts/{acc_id}", dependencies=[Depends(auth)])
def update(acc_id: str, a: Account):
    if acc_id not in DB:
        raise HTTPException(404, "not found")
    DB[acc_id].update(a.model_dump())
    return DB[acc_id]
