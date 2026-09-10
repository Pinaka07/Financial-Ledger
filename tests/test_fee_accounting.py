from tests.helpers import build_system
from wallet_ledger.enums.transaction_type import TransactionType


def test_fee_bearing_transfer_keeps_ledger_balanced():
    """Fix #1: the fee debited from the sender must be credited somewhere
    (the platform revenue wallet), or the ledger's core double-entry
    invariant -- total debits equal total credits -- breaks."""
    system = build_system()
    ws, ts, ledger = system["wallet_service"], system["txn_service"], system["ledger_service"]
    alice = ws.open_wallet("alice", 100_000)
    bob = ws.open_wallet("bob", 0)

    ts.transfer(alice.id, bob.id, 20_000, TransactionType.WALLET_TO_BANK, "fee-key")

    assert ledger.is_balanced()
    assert ledger.total_debits() == ledger.total_credits()
    assert ws.get_balance(system["revenue_wallet"].id) > 0


def test_fee_free_transfer_also_keeps_ledger_balanced():
    system = build_system()
    ws, ts, ledger = system["wallet_service"], system["txn_service"], system["ledger_service"]
    alice = ws.open_wallet("alice", 100_000)
    bob = ws.open_wallet("bob", 0)

    ts.transfer(alice.id, bob.id, 20_000, TransactionType.WALLET_TO_WALLET, "no-fee-key")

    assert ledger.is_balanced()
