# ERP → CRM Customer Sync Service

A scheduled integration that keeps CRM accounts in sync with the ERP customer master over REST APIs. It runs a fast **delta sync every 5 minutes** and a **full reconciliation every night**, so records missing in the CRM are created automatically and the two systems don't drift apart.

> Personal demo project. The ERP and CRM are small mock REST APIs (FastAPI) so the whole thing runs on a laptop. The ERP mock uses SAP-style field names (`KUNNR`, `NAME1`, `ORT01`, `REGIO`…) to mirror a real customer master. It contains no client code or data.

## How it works

```
 ┌──────────────┐  GET /customers?changed_since=…  ┌────────────────┐  find / POST / PATCH  ┌──────────────┐
 │  ERP (mock)  │ ───────────────────────────────▶ │   sync job     │ ────────────────────▶ │  CRM (mock)  │
 │ customer     │      paginated delta API         │ map → validate │   by external_id      │  accounts    │
 │ master       │ ◀─────── GET /customers/{id} ─── │ → hash → upsert│                       │              │
 └──────────────┘        (retry queue)             └───────┬────────┘                       └──────────────┘
                                                           │
                                                 SQLite state: watermark, id cross-ref,
                                                 retry queue, run log
```

1. **Delta fetch.** The job reads only the ERP records changed since the last watermark, page by page, plus any records waiting in the retry queue.
2. **Map and validate.** It converts SAP-style fields to CRM fields:
   - region code → state name
   - phone numbers → `+91 XXXXX XXXXX`
   - posting block → `On Hold`
   - emails are validated

   A record that can't be mapped is rejected with a clear reason.
3. **Change detection.** A SHA-256 hash of the mapped payload is compared with the last synced version, so records that haven't changed are skipped and no API calls are spent on them.
4. **Upsert.** The job updates the record if the CRM already has it and creates it if not. If the local ID cross-reference is lost, it looks the record up by `external_id` in the CRM first, so it **never creates duplicates**.
5. **Resilience.**
   - HTTP 429/5xx responses and network errors are retried with exponential backoff.
   - Records that still fail go into a **retry queue**, which is retried on every run until they succeed or reach 5 attempts.
6. **Audit.** Every run is logged with counts of records fetched, created, updated, unchanged and failed.

## Run the demo (no setup needed)

```bash
pip install -r requirements.txt
python -m sync.demo
```

```
== Run 1 - initial load
   fetched 27 | created 25 | updated 0 | unchanged 0 | failed 2
   ! 100026: email 'billing@@acme' is invalid
   ! 100027: unknown region code 'GA'

== Run 2 - nothing changed (idempotent)
   fetched 2 | created 0 | updated 0 | unchanged 0 | failed 2

== Run 3 - customer blocked + bad email fixed in ERP, CRM briefly returns 503
   WARNING PATCH /accounts/ACC-00003 -> HTTP 503, retry 1/3 in 0.1s
   WARNING PATCH /accounts/ACC-00003 -> HTTP 503, retry 2/3 in 0.1s
   fetched 3 | created 1 | updated 1 | unchanged 0 | failed 1

== Run 4 - nightly full reconciliation re-creates an account deleted in CRM
   fetched 27 | created 1 | updated 0 | unchanged 25 | failed 1
```

## Run it against live APIs

```bash
uvicorn mock_systems.erp:app --port 8001     # terminal 1  (docs at :8001/docs)
uvicorn mock_systems.crm:app --port 8002     # terminal 2
python -m sync.job                           # delta sync
python -m sync.job --full                    # full reconciliation
```

To schedule it, see `crontab.example` (delta every 5 minutes, full sync nightly). Configuration is read from environment variables; see `.env.example`.

## Tests

```bash
python -m pytest -q      # 17 passed
```

The tests cover:

- field mapping and phone normalisation
- multi-page initial load and idempotent re-runs
- delta updates
- bad records going to the retry queue and recovering once fixed at source
- transient 503 retries, and a full outage recovering on the next run
- full reconciliation re-creating missing accounts
- no duplicates when the ID cross-reference is lost

## Project structure

```
mock_systems/
  erp.py       mock ERP customer master API (API-key auth, pagination, delta filter)
  crm.py       mock CRM accounts API (bearer auth, validation, simulated outages)
sync/
  mapping.py   ERP → CRM field mapping + validation + payload hash
  clients.py   API clients with retry/backoff
  state.py     SQLite: watermark, id cross-ref, retry queue, run log
  job.py       the sync job (delta / --full) - cron entry point
  demo.py      in-process walkthrough
tests/
```

## Tech

Python · REST APIs (FastAPI, httpx) · SQLite · cron · pytest
