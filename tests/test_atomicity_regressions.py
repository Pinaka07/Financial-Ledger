from unittest.mock import patch

import pytest

from tests.helpers import build_system
from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import SelfTransferError


def test_self_transfer_is_rejected_and_creates_no_money():
    """
    Regression test for a confirmed bug: {sender_id: -X, receiver_id: +Y}
    collapses to a single dict key when sender == receiver, silently
    dropping the debit and leaving only the credit. Before the fix, a
    300-unit "self-transfer" left the wallet with 300 units *more* than it
    started with, while the ledger still reported itself as balanced.
    """
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)

    with pytest.raises(SelfTransferError):
        ts.transfer(alice.id, alice.id, 300, TransactionType.WALLET_TO_WALLET, "self-key")

    assert ws.get_balance(alice.id) == 1_000


def test_ledger_write_failure_rolls_back_wallet_mutations_and_allows_a_clean_retry():
    """
    Regression test for a confirmed bug: once _apply_wallet_deltas saved
    wallet balances, a *later* ledger-write failure still marked the
    transaction FAILED and released the idempotency key -- even though
    money had already moved. A client retry (correct behavior after
    seeing what looked like a failure) then reapplied the same transfer,
    doubling the debit. Ledger writes are now inside the same atomic
    rollback boundary as the wallet mutation itself.
    """
    system = build_system()
    ws, ts = system["wallet_service"], system["txn_service"]
    alice = ws.open_wallet("alice", 1_000)
    bob = ws.open_wallet("bob", 0)

    call_count = {"n": 0}
    real_record_entries = system["ledger_service"].record_entries

    def flaky_record_entries(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("simulated ledger write failure")
        return real_record_entries(*args, **kwargs)

    with patch.object(system["ledger_service"], "record_entries", side_effect=flaky_record_entries):
        with pytest.raises(ConnectionError):
            ts.transfer(alice.id, bob.id, 300, TransactionType.WALLET_TO_WALLET, "ledger-fail-key")

    # The failed attempt must leave no trace -- wallets rolled back exactly
    # as if the transfer had never been attempted.
    assert ws.get_balance(alice.id) == 1_000
    assert ws.get_balance(bob.id) == 0

    # A clean retry with the same key now succeeds exactly once.
    retried = ts.transfer(alice.id, bob.id, 300, TransactionType.WALLET_TO_WALLET, "ledger-fail-key")
    assert retried.status == TransactionStatus.SUCCESS
    assert ws.get_balance(alice.id) == 700
    assert ws.get_balance(bob.id) == 300
