import threading

from tests.helpers import build_system
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import InvalidTransactionStateError


def test_concurrent_reversals_of_the_same_transaction_apply_exactly_once():
    """
    Two different clients (different idempotency keys) both try to reverse
    the SAME transaction at the same time -- e.g. a user double-tapping a
    'refund' button, or a retried request that got a *new* key instead of
    reusing the old one. Exactly one reversal should succeed; every other
    concurrent attempt should be rejected, and the money should move
    exactly once either way.
    """
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "orig-key-race")

    results, errors = [], []

    def do_reverse(key):
        try:
            results.append(ts.reverse(txn.id, key))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_reverse, args=(f"rev-key-{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1, f"expected exactly one successful reversal, got {len(results)}"
    assert len(errors) == 9
    assert all(isinstance(e, InvalidTransactionStateError) for e in errors)
    assert ws.get_balance(alice.id) == 1_000  # refunded exactly once, not 0 and not double-refunded
    assert ws.get_balance(bob.id) == 0
