from abc import ABC, abstractmethod

from wallet_ledger.models.wallet import Wallet


class WalletRepository(ABC):
    @abstractmethod
    def create(self, wallet: Wallet) -> Wallet:
        ...

    @abstractmethod
    def get(self, wallet_id: str) -> Wallet:
        ...

    @abstractmethod
    def save(self, wallet: Wallet) -> None:
        ...
