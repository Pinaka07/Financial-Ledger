"""
Demo script for the Wallet & Ledger LLD project.

Run: python main.py
"""
import logging

from wallet_ledger.concurrency.lock_registry import LockRegistry
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import InsufficientBalanceError
from wallet_ledger.patterns.observer.console_notifier import ConsoleNotifier, FlakyWebhookNotifier
from wallet_ledger.repository.in_memory_transaction_repository import InMemoryTransactionRepository
from wallet_ledger.repository.in_memory_wallet_repository import InMemoryWalletRepository
from wallet_ledger.services.idempotency_service import IdempotencyService
from wallet_ledger.services.ledger_service import LedgerService
from wallet_ledger.services.transaction_service import TransactionService
from wallet_ledger.services.wallet_service import WalletService

logging.basicConfig(level=logging.WARNING)


def main():
    wallet_repo = InMemoryWalletRepository()
    wallet_service = WalletService(wallet_repo)
    ledger_service = LedgerService()

    revenue_wallet = wallet_service.open_wallet(owner_id="PLATFORM", opening_balance=0)

    txn_service = TransactionService(
        wallet_repository=wallet_repo,
        transaction_repository=InMemoryTransactionRepository(),
        ledger_service=ledger_service,
        idempotency_service=IdempotencyService(),
        lock_registry=LockRegistry(),
        revenue_wallet_id=revenue_wallet.id,
        # FlakyWebhookNotifier always throws -- included to prove it never
        # breaks a successful transfer (fix #7).
        observers=[ConsoleNotifier(), FlakyWebhookNotifier()],
    )

    alice = wallet_service.open_wallet(owner_id="alice", opening_balance=100_000)  # (Rs)1000.00
    bob = wallet_service.open_wallet(owner_id="bob", opening_balance=0)

    print(f"Starting balances -> alice: {alice.balance}, bob: {bob.balance}")

    txn = txn_service.transfer(
        sender_wallet_id=alice.id,
        receiver_wallet_id=bob.id,
        amount=20_000,
        transaction_type=TransactionType.WALLET_TO_BANK,
        idempotency_key="demo-key-1",
    )
    print(f"\nTransaction {txn.id[:8]} -> {txn.status.value}, fee charged: {txn.fee}")
    print(f"alice: {wallet_service.get_balance(alice.id)}")
    print(f"bob: {wallet_service.get_balance(bob.id)}")
    print(f"platform revenue wallet: {wallet_service.get_balance(revenue_wallet.id)}")
    print(f"ledger balanced? {ledger_service.is_balanced()}")

    # Retrying the exact same key returns the cached result -- no double charge.
    same_txn = txn_service.transfer(
        sender_wallet_id=alice.id,
        receiver_wallet_id=bob.id,
        amount=20_000,
        transaction_type=TransactionType.WALLET_TO_BANK,
        idempotency_key="demo-key-1",
    )
    print(f"\nRetried with same idempotency key -> same transaction? {same_txn.id == txn.id}")

    # Insufficient balance: fails, and the key is released so it can be
    # retried later once the sender's balance actually changes.
    try:
        txn_service.transfer(
            sender_wallet_id=bob.id,
            receiver_wallet_id=alice.id,
            amount=1_000_000,
            transaction_type=TransactionType.WALLET_TO_WALLET,
            idempotency_key="demo-key-2",
        )
    except InsufficientBalanceError as e:
        print(f"\nExpected failure on first attempt: {e}")

    wallet_service.topup(bob.id, 1_000_000)
    retried = txn_service.transfer(
        sender_wallet_id=bob.id,
        receiver_wallet_id=alice.id,
        amount=1_000_000,
        transaction_type=TransactionType.WALLET_TO_WALLET,
        idempotency_key="demo-key-2",
    )
    print(f"Same key succeeds after topping up -> {retried.status.value}")

    # Reversing the original fee-bearing transfer refunds everyone,
    # including the platform's fee, and rebalances the ledger.
    reversal = txn_service.reverse(txn.id, "demo-reverse-key")
    print(f"\nReversal {reversal.id[:8]} -> {reversal.status.value}")
    print(f"alice: {wallet_service.get_balance(alice.id)}")
    print(f"bob: {wallet_service.get_balance(bob.id)}")
    print(f"platform revenue wallet: {wallet_service.get_balance(revenue_wallet.id)}")
    print(f"ledger balanced? {ledger_service.is_balanced()}")


if __name__ == "__main__":
    main()
