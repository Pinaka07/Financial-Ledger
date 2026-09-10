from abc import ABC, abstractmethod

from wallet_ledger.models.wallet import Wallet


class TransferStrategy(ABC):
    @abstractmethod
    def calculate_fee(self, amount: int) -> int:
        ...

    @abstractmethod
    def validate(self, sender: Wallet, total_deduction: int) -> None:
        ...
