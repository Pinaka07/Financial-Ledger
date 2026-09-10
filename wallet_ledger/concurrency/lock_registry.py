import threading
from collections import defaultdict


class LockRegistry:
    """
    Fix for: locks attached to a domain object instance (e.g. a `Wallet.lock`
    attribute) silently stop working the moment wallets are fetched from a
    real persistence layer, because an ORM/repository hands back a *new*
    Python object on every query. Two threads "locking the same wallet"
    would actually be locking two unrelated lock instances, and mutual
    exclusion is defeated without any error ever being raised.

    This registry keys locks off wallet_id in one process-wide table
    instead, so the same lock object is always returned no matter how many
    Wallet instances get created for that id. In a real distributed
    deployment this would be replaced by DB row locks
    (SELECT ... FOR UPDATE) or a distributed lock service (e.g. Redis
    Redlock) — the registry is the seam where that swap would happen.
    """

    def __init__(self):
        self._locks: dict[str, threading.RLock] = defaultdict(threading.RLock)
        self._registry_lock = threading.Lock()

    def get_lock(self, wallet_id: str) -> threading.RLock:
        with self._registry_lock:
            return self._locks[wallet_id]
