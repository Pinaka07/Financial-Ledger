from abc import ABC, abstractmethod
from typing import Optional

from wallet_ledger.models.transaction import Transaction


class TransactionRepository(ABC):
    @abstractmethod
    def save(self, transaction: Transaction) -> None:
        ...

    @abstractmethod
    def get(self, transaction_id: str) -> Optional[Transaction]:
        ...
