import threading
import uuid
from dataclasses import dataclass

from wallet_ledger.enums.entry_type import EntryType
from wallet_ledger.models.ledger_entry import LedgerEntry


@dataclass
class LedgerLine:
    """One line to be written -- see LedgerService.record_entries."""
    wallet_id: str
    entry_type: EntryType
    amount: int
    balance_after: int


class LedgerService:
    """
    Append-only ledger. In production this would be a database table,
    periodically archived to cold storage — the same unbounded-growth risk
    that IdempotencyService solves with a TTL applies here too, just on a
    longer time horizon, so entries would be paginated/archived rather than
    kept in memory forever.
    """

    def __init__(self):
        self._entries: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def record_entry(
        self, transaction_id: str, wallet_id: str, entry_type: EntryType, amount: int, balance_after: int
    ) -> LedgerEntry:
        """Convenience wrapper for a single line. Prefer record_entries()
        when writing more than one line for the same transaction (a debit
        and its matching credit) -- see there for why."""
        return self.record_entries(transaction_id, [LedgerLine(wallet_id, entry_type, amount, balance_after)])[0]

    def record_entries(self, transaction_id: str, lines: list[LedgerLine]) -> list[LedgerEntry]:
        """
        Writes every line for one operation (e.g. a transfer's debit and
        credit, plus its fee credit) as a single atomic append.

        This matters because a transaction's debit and credit are only
        meaningful as a pair -- if they were written one call at a time and
        the second call failed after the first had already landed in this
        append-only structure (which, correctly, has no delete), the
        ledger would be left holding a debit with no matching credit
        forever, permanently breaking `is_balanced()` even after any
        wallet-level rollback elsewhere undid the underlying balance
        change. Building every LedgerEntry first (pure, can't fail for
        valid inputs) and appending the whole batch under one lock
        acquisition means there's no window where only some of a
        transaction's lines exist.
        """
        built = [
            LedgerEntry(
                id=str(uuid.uuid4()),
                transaction_id=transaction_id,
                wallet_id=line.wallet_id,
                entry_type=line.entry_type,
                amount=line.amount,
                balance_after=line.balance_after,
            )
            for line in lines
        ]
        with self._lock:
            self._entries.extend(built)
        return built

    def entries_for_transaction(self, transaction_id: str) -> list[LedgerEntry]:
        return [e for e in self._entries if e.transaction_id == transaction_id]

    def total_debits(self) -> int:
        return sum(e.amount for e in self._entries if e.entry_type == EntryType.DEBIT)

    def total_credits(self) -> int:
        return sum(e.amount for e in self._entries if e.entry_type == EntryType.CREDIT)

    def is_balanced(self) -> bool:
        """The core double-entry invariant: total debits must equal total
        credits across the whole ledger. This is the direct check for the
        'fee black hole' bug — it fails if a fee is debited from the sender
        but never credited anywhere."""
        return self.total_debits() == self.total_credits()
