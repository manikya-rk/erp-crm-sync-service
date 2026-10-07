"""Self-contained demo: runs both mock systems in-process and walks through a few sync cycles."""
import logging
import random
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from mock_systems import crm as crm_app, erp as erp_app
from .clients import CRMClient, ERPClient
from .job import run_sync
from .state import StateStore

CITIES = [("Bengaluru", "KA"), ("Pune", "MH"), ("Chennai", "TN"), ("Ahmedabad", "GJ"),
          ("New Delhi", "DL"), ("Hyderabad", "TS"), ("Noida", "UP"), ("Kolkata", "WB")]


def seed(erp_http, n=25):
    random.seed(3)
    for i in range(1, n + 1):
        city, region = CITIES[i % len(CITIES)]
        erp_http.put(f"/api/v1/customers/{100000 + i}", json={
            "KUNNR": str(100000 + i), "NAME1": f"Acme Retail {city} {i}", "ORT01": city, "REGIO": region,
            "SMTP_ADDR": f"accounts{i}@acme-retail.example", "TELF1": f"0{random.randint(7000000000, 9999999999)}",
            "KLIMK": random.choice([50000, 100000, 250000]), "SPERR": False})
    # two records with real-world problems
    erp_http.put("/api/v1/customers/100026", json={"KUNNR": "100026", "NAME1": "Bad Email Traders", "ORT01": "Pune",
                                                   "REGIO": "MH", "SMTP_ADDR": "billing@@acme", "TELF1": ""})
    erp_http.put("/api/v1/customers/100027", json={"KUNNR": "100027", "NAME1": "Unknown Region Co", "ORT01": "Goa",
                                                   "REGIO": "GA", "SMTP_ADDR": "", "TELF1": ""})


def show(title, s):
    print(f"\n== {title}")
    print(f"   fetched {s['fetched']} | created {s['created']} | updated {s['updated']} | "
          f"unchanged {s['unchanged']} | failed {s['failed']}")
    for k, e in s["errors"]:
        print(f"   ! {k}: {e}")


def main():
    logging.basicConfig(level=logging.WARNING, format="   %(levelname)s %(message)s")
    logging.getLogger("sync").addFilter(lambda r: r.levelno < logging.ERROR)  # errors are printed in the summary
    erp_app.DB.clear(); crm_app.DB.clear()
    key = {"X-API-Key": erp_app.API_KEY}
    erp_http = TestClient(erp_app.app, headers=key)
    erp = ERPClient(TestClient(erp_app.app), erp_app.API_KEY, backoff=0.05)
    crm = CRMClient(TestClient(crm_app.app), crm_app.TOKEN, backoff=0.05)
    store = StateStore(str(Path(tempfile.mkdtemp()) / "state.db"))

    seed(erp_http)
    show("Run 1 - initial load", run_sync(erp, crm, store))
    show("Run 2 - nothing changed (idempotent)", run_sync(erp, crm, store))

    erp_http.put("/api/v1/customers/100003", json={**erp_app.DB["100003"], "SPERR": True})
    erp_http.put("/api/v1/customers/100026", json={**erp_app.DB["100026"], "SMTP_ADDR": "billing@badtraders.example"})
    crm_app.FAILURES["remaining"] = 2   # CRM flaps for two calls
    show("Run 3 - customer blocked + bad email fixed in ERP, CRM briefly returns 503", run_sync(erp, crm, store))

    victim = next(a for a in crm_app.DB.values() if a["external_id"] == "100010")
    del crm_app.DB[victim["id"]]
    store.db.execute("DELETE FROM id_xref WHERE external_id='100010'"); store.db.commit()
    show("Run 4 - nightly full reconciliation re-creates an account deleted in CRM", run_sync(erp, crm, store, full=True))

    print(f"\nCRM now holds {len(crm_app.DB)} accounts. Open retry queue:")
    for row in store.retry_report():
        print(f"   {row[0]}  attempts={row[2]}  {row[1]}")


if __name__ == "__main__":
    main()
