import copy
import threading
import time

from wallet_ledger.exceptions.wallet_exceptions import WalletNotFoundError
from wallet_ledger.models.wallet import Wallet
from wallet_ledger.repository.wallet_repository import WalletRepository


class InMemoryWalletRepository(WalletRepository):
    """
    Deliberately simulates a real persistence layer in two ways:

    1. `get()` returns a brand-new Wallet object built from the stored
       state on every call, the same way an ORM query builds a fresh model
       instance per fetch -- so a lock attached to the Wallet object itself
       would silently stop providing mutual exclusion, exactly as it would
       against a real database.
    2. Each call sleeps for `simulated_latency_seconds` to model a
       realistic network/disk round trip. Without this, a get-mutate-save
       sequence finishes in pure Python bytecode so fast that the GIL
       rarely lets two threads interleave inside it, and a lost-update
       race would almost never actually reproduce in a test -- giving
       false confidence that unsynchronized code is safe. A real database
       call takes real time, and that window is exactly where a missing
       lock fails.

    This is why LockRegistry (see tests/test_concurrency.py) is
    load-bearing here, not just theoretical.
    """

    def __init__(self, simulated_latency_seconds: float = 0.002):
        self._state: dict[str, Wallet] = {}
        self._lock = threading.Lock()
        self._simulated_latency_seconds = simulated_latency_seconds

    def create(self, wallet: Wallet) -> Wallet:
        with self._lock:
            self._state[wallet.id] = copy.deepcopy(wallet)
        return self.get(wallet.id)

    def get(self, wallet_id: str) -> Wallet:
        time.sleep(self._simulated_latency_seconds)
        with self._lock:
            stored = self._state.get(wallet_id)
            if stored is None:
                raise WalletNotFoundError(f"Wallet {wallet_id} not found")
            return copy.deepcopy(stored)

    def save(self, wallet: Wallet) -> None:
        time.sleep(self._simulated_latency_seconds)
        with self._lock:
            if wallet.id not in self._state:
                raise WalletNotFoundError(f"Wallet {wallet.id} not found")
            self._state[wallet.id] = copy.deepcopy(wallet)
