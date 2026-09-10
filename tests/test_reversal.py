import pytest

from tests.helpers import build_system
from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import InvalidTransactionStateError


def test_reversing_a_fee_bearing_transfer_fully_restores_balances():
    system = build_system()
    ws, ts, ledger = system["wallet_service"], system["txn_service"], system["ledger_service"]
    alice = ws.open_wallet("alice", 100_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 20_000, TransactionType.WALLET_TO_BANK, "orig-key")
    assert ws.get_balance(alice.id) == 79_500  # 100000 - 20000 - 500 fee
    assert ws.get_balance(system["revenue_wallet"].id) == 500

    reversal = ts.reverse(txn.id, "reverse-key")

    assert reversal.status == TransactionStatus.SUCCESS
    assert reversal.is_reversal is True
    assert reversal.original_transaction_id == txn.id

    # Everyone is back to where they started, fee included.
    assert ws.get_balance(alice.id) == 100_000
    assert ws.get_balance(bob.id) == 0
    assert ws.get_balance(system["revenue_wallet"].id) == 0
    assert ledger.is_balanced()

    original = system["txn_service"].transaction_repository.get(txn.id)
    assert original.status == TransactionStatus.REVERSED


def test_reversing_the_same_transaction_twice_is_rejected():
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "orig-key-2")
    ts.reverse(txn.id, "reverse-key-2")

    with pytest.raises(InvalidTransactionStateError):
        ts.reverse(txn.id, "reverse-key-3")  # a fresh key, but the transaction is already REVERSED


def test_reversing_a_reversal_is_rejected():
    """
    Regression test for a confirmed bug: reversing a reversal actually
    redid the original transfer's money movement, while both the original
    transaction AND its reversal kept claiming REVERSED -- so the
    transaction log lied about whether a transfer was in effect. Undoing a
    reversal must be a fresh transfer, not a "reversal of a reversal."
    """
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "orig-key-4")
    reversal = ts.reverse(txn.id, "reverse-key-4")
    assert ws.get_balance(alice.id) == 1_000  # fully undone

    with pytest.raises(InvalidTransactionStateError):
        ts.reverse(reversal.id, "reverse-key-5")

    # Nothing moved as a side effect of the rejected attempt.
    assert ws.get_balance(alice.id) == 1_000
    assert ws.get_balance(bob.id) == 0


def test_retrying_a_reversal_with_the_same_key_returns_the_cached_result():
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    txn = ts.transfer(alice.id, bob.id, 200, TransactionType.WALLET_TO_WALLET, "orig-key-3")
    first = ts.reverse(txn.id, "shared-reverse-key")
    second = ts.reverse(txn.id, "shared-reverse-key")

    assert first.id == second.id
    assert ws.get_balance(alice.id) == 1_000  # not "double refunded"
