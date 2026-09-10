import pytest

from tests.helpers import build_system
from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import InsufficientBalanceError


def test_successful_wallet_to_wallet_transfer():
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 300, TransactionType.WALLET_TO_WALLET, "key-1")

    assert txn.status == TransactionStatus.SUCCESS
    assert ws.get_balance(alice.id) == 700
    assert ws.get_balance(bob.id) == 300


def test_insufficient_balance_leaves_wallets_untouched():
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 100)
    bob = ws.open_wallet("bob", 0)

    with pytest.raises(InsufficientBalanceError):
        ts.transfer(alice.id, bob.id, 500, TransactionType.WALLET_TO_WALLET, "key-2")

    assert ws.get_balance(alice.id) == 100
    assert ws.get_balance(bob.id) == 0


def test_insufficient_balance_releases_idempotency_key_for_retry():
    """Fix #3: a recoverable failure must not permanently lock the
    idempotency key -- the same key should succeed once the underlying
    condition (low balance) is fixed."""
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 100)
    bob = ws.open_wallet("bob", 0)

    with pytest.raises(InsufficientBalanceError):
        ts.transfer(alice.id, bob.id, 500, TransactionType.WALLET_TO_WALLET, "retry-key")

    ws.topup(alice.id, 1_000)

    txn = ts.transfer(alice.id, bob.id, 500, TransactionType.WALLET_TO_WALLET, "retry-key")

    assert txn.status == TransactionStatus.SUCCESS
    assert ws.get_balance(bob.id) == 500
