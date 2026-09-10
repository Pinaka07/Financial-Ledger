from wallet_ledger.concurrency.lock_registry import LockRegistry
from wallet_ledger.repository.in_memory_transaction_repository import InMemoryTransactionRepository
from wallet_ledger.repository.in_memory_wallet_repository import InMemoryWalletRepository
from wallet_ledger.services.idempotency_service import IdempotencyService
from wallet_ledger.services.ledger_service import LedgerService
from wallet_ledger.services.transaction_service import TransactionService
from wallet_ledger.services.wallet_service import WalletService


def build_system(observers=None):
    """Build a completely fresh, isolated system so tests never share state."""
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
        observers=observers or [],
    )

    return {
        "wallet_service": wallet_service,
        "txn_service": txn_service,
        "ledger_service": ledger_service,
        "revenue_wallet": revenue_wallet,
    }
