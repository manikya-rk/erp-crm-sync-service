"""Thin API clients with retry + exponential backoff for transient failures."""
import logging
import time
import httpx

log = logging.getLogger("sync")
RETRY_STATUS = {429, 500, 502, 503, 504}


class TransientError(RuntimeError):
    pass


def request_with_retry(client: httpx.Client, method: str, url: str, *, retries: int = 4,
                       backoff: float = 0.5, **kw) -> httpx.Response:
    for attempt in range(1, retries + 1):
        try:
            resp = client.request(method, url, **kw)
        except httpx.TransportError as e:
            reason = f"network error: {e}"
        else:
            if resp.status_code not in RETRY_STATUS:
                return resp
            reason = f"HTTP {resp.status_code}"
        if attempt < retries:
            wait = backoff * 2 ** (attempt - 1)
            log.warning("%s %s -> %s, retry %d/%d in %.1fs", method, url, reason, attempt, retries - 1, wait)
            time.sleep(wait)
    raise TransientError(f"{method} {url} failed after {retries} attempts ({reason})")


class ERPClient:
    def __init__(self, client: httpx.Client, api_key: str, backoff: float = 0.5):
        self.c, self.h, self.backoff = client, {"X-API-Key": api_key}, backoff

    def changed_since(self, watermark: str, page_size: int = 50):
        page = 1
        while True:
            r = request_with_retry(self.c, "GET", "/api/v1/customers", headers=self.h, backoff=self.backoff,
                                   params={"changed_since": watermark, "page": page, "page_size": page_size})
            r.raise_for_status()
            body = r.json()
            yield from body["items"]
            if not body["has_more"]:
                return
            page += 1

    def get(self, kunnr: str) -> dict | None:
        r = request_with_retry(self.c, "GET", f"/api/v1/customers/{kunnr}", headers=self.h, backoff=self.backoff)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


class CRMClient:
    def __init__(self, client: httpx.Client, token: str, backoff: float = 0.5):
        self.c, self.h, self.backoff = client, {"Authorization": f"Bearer {token}"}, backoff

    def _req(self, method, url, **kw):
        return request_with_retry(self.c, method, url, headers=self.h, backoff=self.backoff, **kw)

    def find(self, external_id: str) -> dict | None:
        r = self._req("GET", "/accounts", params={"external_id": external_id})
        r.raise_for_status()
        items = r.json()["items"]
        return items[0] if items else None

    def create(self, payload: dict) -> dict:
        r = self._req("POST", "/accounts", json=payload)
        r.raise_for_status()
        return r.json()

    def update(self, crm_id: str, payload: dict) -> dict:
        r = self._req("PATCH", f"/accounts/{crm_id}", json=payload)
        r.raise_for_status()
        return r.json()
