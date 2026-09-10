from wallet_ledger.models.transaction import Transaction
from wallet_ledger.patterns.observer.transaction_observer import TransactionObserver


class ConsoleNotifier(TransactionObserver):
    def on_transaction_completed(self, transaction: Transaction) -> None:
        print(f"[notify] transaction {transaction.id} finished with status {transaction.status.value}")


class FlakyWebhookNotifier(TransactionObserver):
    """
    A deliberately unreliable notifier, used only to prove a point in tests:
    a real webhook/SMS notifier can time out or throw for reasons that have
    nothing to do with whether the money actually moved. See
    TransactionService._notify_observers(), which must isolate this failure
    so it never turns a successful transfer into an error response.
    """

    def on_transaction_completed(self, transaction: Transaction) -> None:
        raise ConnectionError("simulated webhook timeout")
