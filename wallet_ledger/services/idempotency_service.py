import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from wallet_ledger.exceptions.wallet_exceptions import (
    IdempotencyInFlightError,
    IdempotencyPayloadMismatchError,
)


@dataclass
class _IdempotencyRecord:
    payload_hash: str
    status: str  # "IN_PROGRESS" or "COMPLETED"
    result: Optional[Any] = None
    created_at: float = 0.0


class IdempotencyService:
    """
    Fixes three separate bugs from the original design:

    1. Recoverable failures (e.g. InsufficientBalanceError) used to be
       cached as permanently completed, so a user could never retry the
       same idempotency key even after topping up. `complete(..., terminal=False)`
       releases the key instead of freezing it on a business-rule failure.
    2. Reusing the same key with a *different* payload (e.g. a different
       amount) used to silently return the old cached result. It now raises
       IdempotencyPayloadMismatchError so the caller gets a clear conflict
       instead of a wrong, cached answer.
    3. The store used to grow forever. Records now expire after
       `ttl_seconds` and are pruned lazily on access — the same pattern
       Stripe documents for its own idempotency keys (24h window).
    """

    def __init__(self, ttl_seconds: int = 24 * 60 * 60):
        self._records: dict[str, _IdempotencyRecord] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _prune_expired(self) -> None:
        now = time.time()
        expired = [k for k, r in self._records.items() if now - r.created_at > self._ttl_seconds]
        for k in expired:
            del self._records[k]

    def acquire_or_get(self, key: str, payload: dict) -> Optional[Any]:
        """
        Returns the cached result if this exact (key, payload) already
        completed. Returns None if the caller should proceed with fresh
        processing (and has now claimed the key). Raises
        IdempotencyInFlightError if the same key is currently being
        processed elsewhere, or IdempotencyPayloadMismatchError if the key
        is reused with a different payload.
        """
        payload_hash = self._hash_payload(payload)
        with self._lock:
            self._prune_expired()
            record = self._records.get(key)

            if record is None:
                self._records[key] = _IdempotencyRecord(
                    payload_hash=payload_hash, status="IN_PROGRESS", created_at=time.time()
                )
                return None

            if record.payload_hash != payload_hash:
                raise IdempotencyPayloadMismatchError(
                    f"Idempotency key {key!r} was already used with a different request payload"
                )

            if record.status == "IN_PROGRESS":
                raise IdempotencyInFlightError(f"Request with key {key!r} is already being processed")

            return record.result

    def complete(self, key: str, result: Any, terminal: bool = True) -> None:
        """
        terminal=True: cache the result permanently (a genuine success, or
        a business decision that should stay final).
        terminal=False: this was a recoverable failure — release the key
        entirely so the identical request can be retried once the
        underlying condition (e.g. low balance) is fixed.
        """
        with self._lock:
            if terminal:
                if key in self._records:
                    self._records[key].status = "COMPLETED"
                    self._records[key].result = result
            else:
                self._records.pop(key, None)
