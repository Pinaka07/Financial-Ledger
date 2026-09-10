from abc import ABC, abstractmethod

from wallet_ledger.models.transaction import Transaction


class TransactionObserver(ABC):
    @abstractmethod
    def on_transaction_completed(self, transaction: Transaction) -> None:
        ...
