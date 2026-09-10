from wallet_ledger.exceptions.wallet_exceptions import InsufficientBalanceError
from wallet_ledger.models.wallet import Wallet
from wallet_ledger.patterns.strategies.transfer_strategy import TransferStrategy

FLAT_FEE_PAISE = 500  # a flat fee (₹5.00) for withdrawing to a bank account


class WalletToBankStrategy(TransferStrategy):
    """Withdrawal to an external bank account. Charges a flat platform fee.

    The fee this strategy returns is what TransactionService credits to the
    platform's revenue wallet — see the 'fee black hole' fix in
    TransactionService.transfer(). This class only decides *how much* fee
    to charge; where that money goes is the orchestrator's job.
    """

    def calculate_fee(self, amount: int) -> int:
        return FLAT_FEE_PAISE

    def validate(self, sender: Wallet, total_deduction: int) -> None:
        if sender.balance < total_deduction:
            raise InsufficientBalanceError(
                f"Wallet {sender.id} has insufficient balance: has {sender.balance}, needs {total_deduction}"
            )
