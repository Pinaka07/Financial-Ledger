from dataclasses import dataclass, field
from datetime import datetime, timezone

from wallet_ledger.enums.entry_type import EntryType


@dataclass
class LedgerEntry:
    id: str
    transaction_id: str
    wallet_id: str
    entry_type: EntryType
    amount: int
    balance_after: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
