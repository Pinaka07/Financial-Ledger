import copy
import logging
import time
from contextlib import ExitStack

from wallet_ledger.concurrency.lock_registry import LockRegistry
from wallet_ledger.enums.entry_type import EntryType
from wallet_ledger.enums.transaction_status import TransactionStatus
from wallet_ledger.enums.transaction_type import TransactionType
from wallet_ledger.exceptions.wallet_exceptions import (
    IdempotencyInFlightError,
    InsufficientBalanceError,
    InvalidTransactionStateError,
    SelfTransferError,
    TransactionNotFoundError,
)
from wallet_ledger.models.transaction import Transaction
from wallet_ledger.models.wallet import Wallet
from wallet_ledger.patterns.factory.strategy_factory import StrategyFactory
from wallet_ledger.patterns.factory.transaction_factory import TransactionFactory
from wallet_ledger.patterns.observer.transaction_observer import TransactionObserver
from wallet_ledger.repository.transaction_repository import TransactionRepository
from wallet_ledger.repository.wallet_repository import WalletRepository
from wallet_ledger.services.idempotency_service import IdempotencyService
from wallet_ledger.services.ledger_service import LedgerLine, LedgerService

logger = logging.getLogger(__name__)


class TransactionService:
    """
    Orchestrates transfers and reversals. Most of this class exists to fix
    specific vulnerabilities raised across two rounds of review:

      1. Fee black hole      -> the fee is credited to a real revenue
                                 wallet with its own ledger entry, so
                                 total debits always equal total credits.
      2. Partial persistence -> all wallet mutations, their ledger entries,
                                 and the transaction's own status flip are
                                 one atomic unit inside `_apply_wallet_deltas`
                                 (mutation via the main body, ledger + status
                                 via `post_mutation`). If anything in that
                                 unit fails, every wallet already saved this
                                 operation is rolled back to its
                                 pre-operation snapshot before re-raising --
                                 this was extended after a mid-flight
                                 ledger-write failure was shown to leave
                                 wallets moved but the transaction marked
                                 FAILED, letting a client retry double-debit.
      3. Idempotency freezing -> recoverable failures release the
                                 idempotency key instead of caching it
                                 permanently; reusing a key with a
                                 different payload raises instead of
                                 returning stale data.
      4. In-flight collisions -> a concurrent duplicate request polls with
                                 a short backoff instead of crashing.
      5. Lock fragility       -> locks come from a wallet_id-keyed
                                 LockRegistry, never from the Wallet object,
                                 and every wallet touched by an operation
                                 (2 for a fee-free transfer, 3 with a fee
                                 or a reversal) is locked together, in
                                 sorted order, via `_apply_wallet_deltas`.
      7. Fragile observers    -> each observer call is isolated so a
                                 notification failure can never turn a
                                 successful operation into an error
                                 response.
      9. Self-transfer        -> sender == receiver is rejected outright;
                                 left unchecked, it collapsed a two-key
                                 delta dict into one key, silently dropping
                                 the debit and minting money on credit.
    """

    def __init__(
        self,
        wallet_repository: WalletRepository,
        transaction_repository: TransactionRepository,
        ledger_service: LedgerService,
        idempotency_service: IdempotencyService,
        lock_registry: LockRegistry,
        revenue_wallet_id: str,
        observers: list[TransactionObserver] | None = None,
    ):
        self.wallet_repository = wallet_repository
        self.transaction_repository = transaction_repository
        self.ledger_service = ledger_service
        self.idempotency_service = idempotency_service
        self.lock_registry = lock_registry
        self.revenue_wallet_id = revenue_wallet_id
        self.observers = observers or []

    def _wait_for_idempotency_slot(self, key: str, payload: dict, max_wait_seconds: float):
        """Fix #4: poll with exponential backoff instead of letting a
        concurrent duplicate crash with an unhandled error."""
        deadline = time.time() + max_wait_seconds
        backoff = 0.02
        while True:
            try:
                return self.idempotency_service.acquire_or_get(key, payload)
            except IdempotencyInFlightError:
                if time.time() >= deadline:
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 2, 0.25)

    def _notify_observers(self, transaction: Transaction) -> None:
        """Fix #7: isolate each observer so one failing notifier can never
        surface as a failed operation to the caller."""
        for observer in self.observers:
            try:
                observer.on_transaction_completed(transaction)
            except Exception:
                logger.exception(
                    "observer %s raised while handling transaction %s", observer, transaction.id
                )

    def _apply_wallet_deltas(self, deltas: dict[str, int], pre_check=None, post_mutation=None) -> dict[str, Wallet]:
        """
        Atomically applies a set of signed balance changes across any
        number of wallets (positive = credit, negative = debit).

        Every wallet involved is locked together, in sorted order, via a
        shared ExitStack -- generalizing what used to be a hard-coded
        two-lock acquisition so the same helper works for a plain transfer
        (2 wallets), a fee-bearing transfer (3 wallets), and a reversal (2
        or 3 wallets), while still avoiding deadlocks between operations
        that touch overlapping wallets in different orders.

        `pre_check`, if given, runs after every wallet is fetched but
        before anything is mutated -- still inside the same locks -- so
        strategy-specific validation (e.g. "does the sender actually have
        enough balance?") can't race against the mutation it's guarding.

        `post_mutation`, if given, runs after every wallet in this call has
        been mutated *and saved*, but is still covered by the same
        rollback boundary as the mutation itself: if it raises (e.g. a
        ledger write fails), every wallet already saved during this call
        is rolled back to its pre-call snapshot before the exception
        propagates. This closes a real gap that existed here: without it,
        wallet balances could be durably committed while the ledger write
        describing that movement failed, and the caller would mark the
        transaction FAILED and release its idempotency key even though
        money had already moved -- which lets a client's retry (correct
        behavior on their end, since they saw a failure) apply the same
        movement a second time. Reproduced and confirmed with a flaky
        ledger mock before this fix; see tests/test_atomicity_regressions.py.

        If any wallet lacks the balance for its debit, or any save() call
        fails partway through, every wallet already saved during this call
        is rolled back to its pre-call snapshot before the exception
        propagates -- nothing partial is ever left visible.
        """
        wallet_ids = sorted(deltas.keys())
        saved_originals: list[Wallet] = []

        with ExitStack() as stack:
            for wallet_id in wallet_ids:
                stack.enter_context(self.lock_registry.get_lock(wallet_id))

            wallets = {wid: self.wallet_repository.get(wid) for wid in wallet_ids}
            snapshots = {wid: copy.deepcopy(w) for wid, w in wallets.items()}

            if pre_check is not None:
                pre_check(wallets)

            try:
                for wallet_id, delta in deltas.items():
                    wallet = wallets[wallet_id]
                    if delta >= 0:
                        wallet.credit(delta)
                    else:
                        wallet.debit(-delta)

                for wallet_id in wallet_ids:
                    self.wallet_repository.save(wallets[wallet_id])
                    saved_originals.append(snapshots[wallet_id])

                if post_mutation is not None:
                    post_mutation(wallets)

                return wallets

            except Exception:
                for original in saved_originals:
                    self.wallet_repository.save(original)
                raise

    def transfer(
        self,
        sender_wallet_id: str,
        receiver_wallet_id: str,
        amount: int,
        transaction_type: TransactionType,
        idempotency_key: str,
        max_wait_seconds: float = 2.0,
    ) -> Transaction:
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")

        if sender_wallet_id == receiver_wallet_id:
            # Without this guard, {sender_id: -total_deduction, receiver_id:
            # +amount} collapses to a single dict key when sender == receiver,
            # silently dropping the debit and leaving only the credit --
            # confirmed to actually mint money out of nothing before this fix.
            raise SelfTransferError(f"Cannot transfer from wallet {sender_wallet_id} to itself")

        payload = {
            "operation": "transfer",
            "sender": sender_wallet_id,
            "receiver": receiver_wallet_id,
            "amount": amount,
            "type": transaction_type.value,
        }
        cached = self._wait_for_idempotency_slot(idempotency_key, payload, max_wait_seconds)
        if cached is not None:
            return cached

        strategy = StrategyFactory.get_strategy(transaction_type)
        fee = strategy.calculate_fee(amount)
        total_deduction = amount + fee

        transaction = TransactionFactory.create(
            sender_wallet_id, receiver_wallet_id, amount, fee, transaction_type, idempotency_key
        )
        transaction.status = TransactionStatus.PROCESSING
        self.transaction_repository.save(transaction)

        deltas = {sender_wallet_id: -total_deduction, receiver_wallet_id: amount}
        if fee > 0:
            deltas[self.revenue_wallet_id] = deltas.get(self.revenue_wallet_id, 0) + fee

        def pre_check(wallets: dict[str, Wallet]) -> None:
            strategy.validate(wallets[sender_wallet_id], total_deduction)

        def post_mutation(wallets: dict[str, Wallet]) -> None:
            lines = [
                LedgerLine(sender_wallet_id, EntryType.DEBIT, total_deduction, wallets[sender_wallet_id].balance),
                LedgerLine(receiver_wallet_id, EntryType.CREDIT, amount, wallets[receiver_wallet_id].balance),
            ]
            if fee > 0:
                lines.append(
                    LedgerLine(self.revenue_wallet_id, EntryType.CREDIT, fee, wallets[self.revenue_wallet_id].balance)
                )
            self.ledger_service.record_entries(transaction.id, lines)
            # Folding the status flip in here too means wallets, ledger
            # entries, and the transaction's own SUCCESS status all commit
            # or roll back together -- nothing outside this call can fail
            # and leave money moved but the transaction still saying it
            # wasn't.
            transaction.status = TransactionStatus.SUCCESS
            self.transaction_repository.save(transaction)

        try:
            self._apply_wallet_deltas(deltas, pre_check=pre_check, post_mutation=post_mutation)
            self.idempotency_service.complete(idempotency_key, transaction, terminal=True)
            self._notify_observers(transaction)
            return transaction

        except InsufficientBalanceError as e:
            self._fail_transaction(transaction, str(e))
            self.idempotency_service.complete(idempotency_key, None, terminal=False)
            self._notify_observers(transaction)
            raise

        except Exception as e:
            self._fail_transaction(transaction, str(e))
            self.idempotency_service.complete(idempotency_key, None, terminal=False)
            self._notify_observers(transaction)
            raise

    def reverse(
        self,
        transaction_id: str,
        idempotency_key: str,
        max_wait_seconds: float = 2.0,
    ) -> Transaction:
        """
        Reverses a previously SUCCESSFUL transaction in full, fee included.

        Real payment systems often treat the fee as non-refundable on a
        reversal -- that's a business-policy decision, not a technical
        constraint, and would just mean dropping the revenue-wallet delta
        below. This demo refunds everything, which keeps the ledger's
        debit=credit invariant trivial to verify either way.

        The idempotency check runs *before* the status check, not after,
        so a retried reversal request (same key, e.g. after a client
        timeout) returns the original cached result instead of incorrectly
        failing on "transaction is already REVERSED".

        A transaction-scoped lock (via the same LockRegistry used for
        wallets, keyed by a namespaced string so it can never collide with
        a wallet id) guards the read-check-claim sequence below. Without
        it, two concurrent reversal requests using *different* idempotency
        keys could both read the original transaction as SUCCESS before
        either had saved it as REVERSED, and both would proceed to refund
        it -- this actually happened in testing and is fixed by claiming
        the reversal (flipping the original to REVERSED) before doing any
        fund movement, not after.
        """
        payload = {"operation": "reverse", "original_transaction_id": transaction_id}
        cached = self._wait_for_idempotency_slot(idempotency_key, payload, max_wait_seconds)
        if cached is not None:
            return cached

        transaction_lock = self.lock_registry.get_lock(f"transaction-reversal:{transaction_id}")
        with transaction_lock:
            original = self.transaction_repository.get(transaction_id)
            if original is None:
                self.idempotency_service.complete(idempotency_key, None, terminal=False)
                raise TransactionNotFoundError(f"Transaction {transaction_id} not found")

            if original.is_reversal:
                # Without this guard, reversing a reversal actually redoes
                # the original transfer's money movement, while BOTH the
                # original transaction and the reversal keep claiming
                # REVERSED -- the transaction log ends up lying about
                # whether a transfer is currently in effect. If you need
                # to undo a reversal, that's a new transfer, not a
                # "reversal of a reversal."
                self.idempotency_service.complete(idempotency_key, None, terminal=False)
                raise InvalidTransactionStateError(
                    f"Cannot reverse transaction {transaction_id}: it is itself a reversal"
                )

            if original.status != TransactionStatus.SUCCESS:
                self.idempotency_service.complete(idempotency_key, None, terminal=False)
                raise InvalidTransactionStateError(
                    f"Cannot reverse transaction {transaction_id} in status {original.status.value}"
                )

            reversal = TransactionFactory.create_reversal(original, idempotency_key)
            reversal.status = TransactionStatus.PROCESSING
            self.transaction_repository.save(reversal)

            # Claim the reversal immediately, before any fund movement, so
            # a second concurrent caller (blocked on transaction_lock until
            # now) sees REVERSED -- not SUCCESS -- the moment it gets in.
            original.status = TransactionStatus.REVERSED
            self.transaction_repository.save(original)

            total_to_return = original.amount + original.fee
            deltas = {
                original.sender_wallet_id: total_to_return,
                original.receiver_wallet_id: -original.amount,
            }
            if original.fee > 0:
                deltas[self.revenue_wallet_id] = deltas.get(self.revenue_wallet_id, 0) - original.fee

            try:
                def post_mutation(wallets: dict[str, Wallet]) -> None:
                    lines = [
                        LedgerLine(
                            original.sender_wallet_id, EntryType.CREDIT, total_to_return,
                            wallets[original.sender_wallet_id].balance,
                        ),
                        LedgerLine(
                            original.receiver_wallet_id, EntryType.DEBIT, original.amount,
                            wallets[original.receiver_wallet_id].balance,
                        ),
                    ]
                    if original.fee > 0:
                        lines.append(
                            LedgerLine(
                                self.revenue_wallet_id, EntryType.DEBIT, original.fee,
                                wallets[self.revenue_wallet_id].balance,
                            )
                        )
                    self.ledger_service.record_entries(reversal.id, lines)
                    reversal.status = TransactionStatus.SUCCESS
                    self.transaction_repository.save(reversal)

                self._apply_wallet_deltas(deltas, post_mutation=post_mutation)

                self.idempotency_service.complete(idempotency_key, reversal, terminal=True)
                self._notify_observers(reversal)
                return reversal

            except InsufficientBalanceError as e:
                # The original receiver no longer holds enough balance to
                # give the funds back (e.g. they've already spent it
                # elsewhere). The claim above was premature in this case --
                # undo it so the transaction honestly reflects that it was
                # never actually reversed. A real system would route this
                # to manual/compliance review rather than leave it silently
                # unresolved.
                original.status = TransactionStatus.SUCCESS
                self.transaction_repository.save(original)
                self._fail_transaction(reversal, str(e))
                self.idempotency_service.complete(idempotency_key, None, terminal=False)
                self._notify_observers(reversal)
                raise

            except Exception as e:
                original.status = TransactionStatus.SUCCESS
                self.transaction_repository.save(original)
                self._fail_transaction(reversal, str(e))
                self.idempotency_service.complete(idempotency_key, None, terminal=False)
                self._notify_observers(reversal)
                raise

    def _fail_transaction(self, transaction: Transaction, reason: str) -> None:
        transaction.status = TransactionStatus.FAILED
        transaction.failure_reason = reason
        self.transaction_repository.save(transaction)
