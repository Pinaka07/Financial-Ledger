from dataclasses import dataclass

from wallet_ledger.exceptions.wallet_exceptions import InsufficientBalanceError


@dataclass
class Wallet:
    """
    Balance is stored as an integer in the currency's minor unit (paise for
    INR), never as a float. Floating-point arithmetic on money is a classic
    source of off-by-a-fraction-of-a-paise bugs that only show up after
    thousands of transactions — not worth the risk for a ledger that must
    balance exactly.
    """

    id: str
    owner_id: str
    balance: int
    currency: str = "INR"

    def debit(self, amount: int) -> int:
        if amount <= 0:
            raise ValueError("Debit amount must be positive")
        if self.balance < amount:
            raise InsufficientBalanceError(
                f"Wallet {self.id} has insufficient balance: has {self.balance}, needs {amount}"
            )
        self.balance -= amount
        return self.balance

    def credit(self, amount: int) -> int:
        if amount <= 0:
            raise ValueError("Credit amount must be positive")
        self.balance += amount
        return self.balance
