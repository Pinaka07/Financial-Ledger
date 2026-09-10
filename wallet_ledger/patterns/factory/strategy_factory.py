from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.patterns.strategies.transfer_strategy import TransferStrategy
from wallet_ledger.patterns.strategies.wallet_to_bank_strategy import WalletToBankStrategy
from wallet_ledger.patterns.strategies.wallet_to_wallet_strategy import WalletToWalletStrategy


class StrategyFactory:
    _strategies: dict[TransactionType, TransferStrategy] = {
        TransactionType.WALLET_TO_WALLET: WalletToWalletStrategy(),
        TransactionType.WALLET_TO_BANK: WalletToBankStrategy(),
    }

    @classmethod
    def get_strategy(cls, transaction_type: TransactionType) -> TransferStrategy:
        strategy = cls._strategies.get(transaction_type)
        if strategy is None:
            raise ValueError(f"No strategy registered for {transaction_type}")
        return strategy
