import pytest

from tests.helpers import build_system
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import IdempotencyPayloadMismatchError


def test_same_key_same_payload_returns_cached_transaction_without_double_charge():
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    first = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "dup-key")
    second = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "dup-key")

    assert first.id == second.id
    assert ws.get_balance(alice.id) == 800  # not double-debited


def test_same_key_different_payload_raises_conflict():
    """Fix #3b: reusing a key with a different amount must not silently
    return the old cached result."""
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "shared-key")

    with pytest.raises(IdempotencyPayloadMismatchError):
        ts.transfer(alice.id, bob.id, 999, TransactionType.WALLET_TO_WALLET, "shared-key")
