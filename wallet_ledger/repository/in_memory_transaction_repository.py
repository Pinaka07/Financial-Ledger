import threading
from typing import Optional

from wallet_ledger.models.transaction import Transaction
from wallet_ledger.repository.transaction_repository import TransactionRepository


class InMemoryTransactionRepository(TransactionRepository):
    def __init__(self):
        self._transactions: dict[str, Transaction] = {}
        self._lock = threading.Lock()

    def save(self, transaction: Transaction) -> None:
        with self._lock:
            self._transactions[transaction.id] = transaction

    def get(self, transaction_id: str) -> Optional[Transaction]:
        return self._transactions.get(transaction_id)
