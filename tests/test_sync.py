from mock_systems import crm as crm_app
from sync.job import run_sync
from tests.conftest import customer


def load(erp_http, *custs):
    for c in custs:
        erp_http.put(f"/api/v1/customers/{c['KUNNR']}", json=c)


def test_initial_load_and_idempotency(env):
    erp_http, erp, crm, store = env
    load(erp_http, *[customer(n) for n in range(1, 121)])  # > 2 pages
    s = run_sync(erp, crm, store)
    assert s["created"] == 120 and len(crm_app.DB) == 120
    s2 = run_sync(erp, crm, store)
    assert s2["fetched"] == 0 and len(crm_app.DB) == 120


def test_delta_update(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1), customer(2))
    run_sync(erp, crm, store)
    load(erp_http, customer(2, KLIMK=5000))
    s = run_sync(erp, crm, store)
    assert s["fetched"] == 1 and s["updated"] == 1
    assert next(a for a in crm_app.DB.values() if a["external_id"] == "2")["credit_limit"] == 5000


def test_bad_record_goes_to_retry_queue_then_recovers(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1), customer(2, REGIO="ZZ"))
    s = run_sync(erp, crm, store)
    assert s["created"] == 1 and s["failed"] == 1 and store.pending_retries() == ["2"]
    load(erp_http, customer(2))  # fixed at source
    s = run_sync(erp, crm, store)
    assert s["created"] == 1 and store.pending_retries() == []


def test_transient_503_is_retried(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1))
    crm_app.FAILURES["remaining"] = 2
    s = run_sync(erp, crm, store)
    assert s["created"] == 1 and s["failed"] == 0


def test_persistent_outage_queues_for_next_run(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1))
    crm_app.FAILURES["remaining"] = 10
    s = run_sync(erp, crm, store)
    assert s["failed"] == 1 and store.pending_retries() == ["1"]
    crm_app.FAILURES["remaining"] = 0
    s = run_sync(erp, crm, store)
    assert s["created"] == 1 and store.pending_retries() == []


def test_full_reconciliation_recreates_missing(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1), customer(2))
    run_sync(erp, crm, store)
    crm_app.DB.clear()
    store.db.execute("DELETE FROM id_xref"); store.db.commit()
    s = run_sync(erp, crm, store, full=True)
    assert s["created"] == 2 and len(crm_app.DB) == 2


def test_no_duplicate_when_xref_lost(env):
    erp_http, erp, crm, store = env
    load(erp_http, customer(1))
    run_sync(erp, crm, store)
    store.db.execute("DELETE FROM id_xref"); store.db.commit()
    s = run_sync(erp, crm, store, full=True)
    assert s["updated"] == 1 and len(crm_app.DB) == 1
