import threading

from tests.helpers import build_system
from wallet_ledger.enums.transaction_type import TransactionType


def test_concurrent_transfers_never_lose_updates():
    """
    Fix #5: locks are keyed by wallet_id in a shared LockRegistry rather
    than attached to the Wallet object. InMemoryWalletRepository
    deliberately returns a fresh object on every get() (like a real ORM
    would), so if locking were done on the fetched object instead of the
    registry, this test would intermittently fail with a lost update --
    the classic concurrent read-modify-write bug.
    """
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 100_000)
    bob = ws.open_wallet("bob", 0)

    num_threads = 25
    amount_each = 1_000
    errors = []

    def do_transfer(i):
        try:
            ts.transfer(alice.id, bob.id, amount_each, TransactionType.WALLET_TO_WALLET, f"concurrent-{i}")
        except Exception as e:  # pragma: no cover - surfaced via `errors` assertion below
            errors.append(e)

    threads = [threading.Thread(target=do_transfer, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"unexpected errors during concurrent transfers: {errors}"
    assert ws.get_balance(alice.id) == 100_000 - num_threads * amount_each
    assert ws.get_balance(bob.id) == num_threads * amount_each
