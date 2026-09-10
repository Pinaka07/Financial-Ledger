from wallet_ledger.exceptions.wallet_exceptions import InsufficientBalanceError
from wallet_ledger.models.wallet import Wallet
from wallet_ledger.patterns.strategies.transfer_strategy import TransferStrategy


class WalletToWalletStrategy(TransferStrategy):
    """Peer-to-peer wallet transfer. No platform fee."""

    def calculate_fee(self, amount: int) -> int:
        return 0

    def validate(self, sender: Wallet, total_deduction: int) -> None:
        if sender.balance < total_deduction:
            raise InsufficientBalanceError(
                f"Wallet {sender.id} has insufficient balance: has {sender.balance}, needs {total_deduction}"
            )
