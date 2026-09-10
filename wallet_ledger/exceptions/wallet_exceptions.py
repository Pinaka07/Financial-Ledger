class WalletError(Exception):
    """Base class for every error this system raises."""


class WalletNotFoundError(WalletError):
    pass


class InsufficientBalanceError(WalletError):
    """A recoverable, business-level failure. See IdempotencyService.complete()
    for why this is treated differently from an unexpected/system error."""


class InvalidTransactionStateError(WalletError):
    pass


class TransactionNotFoundError(WalletError):
    pass


class SelfTransferError(WalletError):
    """Raised when a transfer's sender and receiver are the same wallet.
    Left unchecked, this collapses a dict literal like
    {sender_id: -total_deduction, receiver_id: +amount} down to a single
    key -- silently dropping the debit and leaving only the credit, which
    creates money out of nothing even though the ledger entries (computed
    independently) look perfectly balanced on paper."""


class IdempotencyPayloadMismatchError(WalletError):
    """Raised when a client reuses an idempotency key with a different
    request payload (e.g. a different amount). Prevents silently returning
    a cached result for a request the client never actually made."""


class IdempotencyInFlightError(WalletError):
    """Raised when a second request arrives with the same idempotency key
    while the first one is still being processed."""
