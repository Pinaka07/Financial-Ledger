import uuid

from wallet_ledger.models.wallet import Wallet
from wallet_ledger.repository.wallet_repository import WalletRepository


class WalletService:
    def __init__(self, wallet_repository: WalletRepository):
        self.wallet_repository = wallet_repository

    def open_wallet(self, owner_id: str, opening_balance: int = 0, currency: str = "INR") -> Wallet:
        wallet = Wallet(id=str(uuid.uuid4()), owner_id=owner_id, balance=opening_balance, currency=currency)
        return self.wallet_repository.create(wallet)

    def get_balance(self, wallet_id: str) -> int:
        return self.wallet_repository.get(wallet_id).balance

    def topup(self, wallet_id: str, amount: int) -> int:
        wallet = self.wallet_repository.get(wallet_id)
        wallet.credit(amount)
        self.wallet_repository.save(wallet)
        return wallet.balance
