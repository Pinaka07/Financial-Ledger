import uuid

from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.models.transaction import Transaction


class TransactionFactory:
    @staticmethod
    def create(
        sender_wallet_id: str,
        receiver_wallet_id: str,
        amount: int,
        fee: int,
        transaction_type: TransactionType,
        idempotency_key: str,
    ) -> Transaction:
        return Transaction(
            id=str(uuid.uuid4()),
            sender_wallet_id=sender_wallet_id,
            receiver_wallet_id=receiver_wallet_id,
            amount=amount,
            fee=fee,
            type=transaction_type,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def create_reversal(original: Transaction, idempotency_key: str) -> Transaction:
        """Money flows back the opposite way: the original receiver becomes
        the sender, and vice versa. The reversal itself carries no separate
        fee -- it's undoing a transfer, not making a new one."""
        return Transaction(
            id=str(uuid.uuid4()),
            sender_wallet_id=original.receiver_wallet_id,
            receiver_wallet_id=original.sender_wallet_id,
            amount=original.amount,
            fee=0,
            type=original.type,
            idempotency_key=idempotency_key,
            is_reversal=True,
            original_transaction_id=original.id,
        )
