from enum import Enum


class TransactionType(str, Enum):
    WALLET_TO_WALLET = "WALLET_TO_WALLET"
    WALLET_TO_BANK = "WALLET_TO_BANK"
