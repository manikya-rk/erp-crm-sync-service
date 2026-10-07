"""ERP -> CRM customer sync job.

Delta mode (default, every 5 min via cron): pulls records changed since the last
watermark plus anything in the retry queue.
Full mode (--full, nightly): re-reads every ERP record so any account missing in
the CRM is auto-created and drift is corrected.
"""
import argparse
import logging
import os

import httpx

from .clients import CRMClient, ERPClient, TransientError
from .mapping import MappingError, erp_to_crm, payload_hash
from .state import StateStore, utcnow

log = logging.getLogger("sync")


def sync_one(rec: dict, crm: CRMClient, store: StateStore) -> str:
    payload = erp_to_crm(rec)
    h = payload_hash(payload)
    known = store.lookup(rec["KUNNR"])
    if known and known[1] == h:
        return "unchanged"
    crm_id = known[0] if known else None
    if not crm_id:  # not in our xref - check the CRM before creating to avoid duplicates
        existing = crm.find(rec["KUNNR"])
        crm_id = existing["id"] if existing else None
    if crm_id:
        crm.update(crm_id, payload)
        result = "updated"
    else:
        crm_id = crm.create(payload)["id"]
        result = "created"
    store.remember(rec["KUNNR"], crm_id, h)
    return result


def run_sync(erp: ERPClient, crm: CRMClient, store: StateStore, full: bool = False) -> dict:
    started = utcnow()
    s = {"fetched": 0, "created": 0, "updated": 0, "unchanged": 0, "failed": 0, "errors": []}
    watermark = "" if full else store.get_watermark()
    new_watermark = store.get_watermark()

    records = {r["KUNNR"]: r for r in erp.changed_since(watermark)}
    for kunnr in store.pending_retries():
        if kunnr not in records and (r := erp.get(kunnr)):
            records[kunnr] = r
    s["fetched"] = len(records)

    for kunnr, rec in records.items():
        try:
            s[sync_one(rec, crm, store)] += 1
            store.clear_retry(kunnr)
        except (MappingError, TransientError, httpx.HTTPStatusError) as e:
            s["failed"] += 1
            s["errors"].append((kunnr, str(e)))
            store.queue_retry(kunnr, str(e))
            log.error("%s: %s", kunnr, e)
        new_watermark = max(new_watermark, rec["CHANGED_AT"])

    store.set_watermark(new_watermark)
    store.log_run(started, "full" if full else "delta", s)
    return s


def main():
    p = argparse.ArgumentParser(description="Sync ERP customers into CRM accounts")
    p.add_argument("--full", action="store_true", help="full reconciliation instead of delta")
    p.add_argument("--state", default=os.getenv("SYNC_STATE_DB", "sync_state.db"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    erp = ERPClient(httpx.Client(base_url=os.getenv("ERP_URL", "http://localhost:8001"), timeout=10),
                    os.getenv("ERP_API_KEY", "erp-demo-key"))
    crm = CRMClient(httpx.Client(base_url=os.getenv("CRM_URL", "http://localhost:8002"), timeout=10),
                    os.getenv("CRM_TOKEN", "crm-demo-token"))
    s = run_sync(erp, crm, StateStore(a.state), full=a.full)
    log.info("fetched=%d created=%d updated=%d unchanged=%d failed=%d",
             s["fetched"], s["created"], s["updated"], s["unchanged"], s["failed"])


if __name__ == "__main__":
    main()
