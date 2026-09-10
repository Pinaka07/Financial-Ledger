from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType


@dataclass
class Transaction:
    id: str
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: int
    fee: int
    type: TransactionType
    idempotency_key: str
    status: TransactionStatus = TransactionStatus.INITIATED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    failure_reason: Optional[str] = None
    is_reversal: bool = False
    original_transaction_id: Optional[str] = None
