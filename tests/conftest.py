import pytest
from fastapi.testclient import TestClient

from mock_systems import crm as crm_app, erp as erp_app
from sync.clients import CRMClient, ERPClient
from sync.state import StateStore


@pytest.fixture
def env(tmp_path):
    erp_app.DB.clear(); crm_app.DB.clear(); crm_app.FAILURES["remaining"] = 0
    erp_http = TestClient(erp_app.app, headers={"X-API-Key": erp_app.API_KEY})
    erp = ERPClient(TestClient(erp_app.app), erp_app.API_KEY, backoff=0)
    crm = CRMClient(TestClient(crm_app.app), crm_app.TOKEN, backoff=0)
    return erp_http, erp, crm, StateStore(str(tmp_path / "s.db"))


def customer(n, **over):
    c = {"KUNNR": str(n), "NAME1": f"Cust {n}", "ORT01": "bengaluru", "REGIO": "KA",
         "SMTP_ADDR": f"a{n}@x.example", "TELF1": "09876543210", "KLIMK": 1000, "SPERR": False}
    c.update(over)
    return c
