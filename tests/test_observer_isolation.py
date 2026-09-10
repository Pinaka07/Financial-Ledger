from tests.helpers import build_system
from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.patterns.observer.console_notifier import FlakyWebhookNotifier


def test_flaky_observer_does_not_break_a_successful_transfer():
    """Fix #7: an observer that throws must not surface as a failed
    transfer -- the money already moved, and that fact can't depend on an
    unrelated notification succeeding."""
    system = build_system(observers=[FlakyWebhookNotifier()])
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 100, TransactionType.WALLET_TO_WALLET, "obs-key")

    assert txn.status == TransactionStatus.SUCCESS
    assert ws.get_balance(bob.id) == 100
