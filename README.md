# Wallet & Ledger System (LLD project)
[![CI](https://github.com/Pinaka07/Financial-Ledger/actions/workflows/tests.yml/badge.svg)](https://github.com/Pinaka07/Financial-Ledger/actions/workflows/tests.yml)

An in-memory wallet and double-entry ledger engine — the core logic behind
a UPI/wallet-style payment flow, without any web framework or database
attached. Built to demonstrate low-level design: class responsibilities,
design patterns, concurrency correctness, and idempotency handling.

## Running it

```bash
pip install -r requirements.txt
python main.py          # runs a scripted demo end to end
python -m pytest -v     # runs the full test suite
```

## Architecture

- `models/` — plain data: `User`, `Wallet`, `Transaction`, `LedgerEntry`
- `enums/` — `TransactionStatus`, `TransactionType`, `EntryType`
- `services/` — orchestration: `WalletService`, `TransactionService`,
  `LedgerService`, `IdempotencyService`
- `patterns/` — the swappable behavior: Strategy (`WalletToWalletStrategy`,
  `WalletToBankStrategy`), Factory (`StrategyFactory`,
  `TransactionFactory`), Observer (`TransactionObserver` and its
  implementations)
- `repository/` — persistence interfaces plus in-memory implementations,
  isolated behind an abstract base so a SQL-backed repository could be
  swapped in without touching `TransactionService`
- `concurrency/` — `LockRegistry`, a wallet_id-keyed lock table

## Design decisions worth explaining in an interview

**Money is an integer, never a float.** Balances are stored in minor units
(paise) to avoid floating-point rounding errors compounding across
thousands of transactions.

**`InMemoryWalletRepository` simulates a real database on purpose.** It
returns a brand-new `Wallet` object on every `get()` (like an ORM query
would) and sleeps briefly on every call to model network/disk latency.
Without this, locking bugs that only appear against a real database would
silently "work" in an in-memory demo and only surface in production.

## Known failure modes this design addresses

An earlier version of this design was reviewed and found to have seven
concrete bugs. Each is fixed here, and each has a test proving it:

| # | Failure mode | Fix | Proven by |
|---|---|---|---|
| 1 | **Fee black hole** — a fee was debited from the sender but never credited anywhere, breaking the ledger's debit=credit invariant | Fees are credited to a dedicated platform revenue wallet with their own ledger entry | `test_fee_accounting.py` |
| 2 | **Partial persistence** — balance mutations happened before all writes succeeded, so a failure mid-transfer could leave one wallet debited with no matching credit | All mutations happen on in-memory copies first; every wallet already saved this transfer is rolled back to its pre-transfer snapshot if a later step fails | `test_transaction_service.py::test_insufficient_balance_leaves_wallets_untouched` |
| 3 | **Idempotency freezing** — a recoverable failure (e.g. insufficient balance) was cached as a permanent result, permanently blocking retries under that key | Recoverable failures release the key; a reused key with a different payload raises a conflict instead of returning stale data | `test_transaction_service.py::test_insufficient_balance_releases_idempotency_key_for_retry`, `test_idempotency.py` |
| 4 | **Unhandled in-flight collisions** — a concurrent duplicate request crashed instead of waiting | The orchestrator polls with exponential backoff before giving up | `TransactionService._wait_for_idempotency_slot` |
| 5 | **Lock fragility** — locks lived on the `Wallet` object, which silently stops providing mutual exclusion once a real persistence layer returns a fresh object per fetch | Locks come from a `wallet_id`-keyed `LockRegistry`, never from the object itself | `test_concurrency.py` |
| 6 | **Unbounded growth** — the idempotency store grew forever | Records expire after a configurable TTL (24h default, same window Stripe documents) and are pruned lazily on access | `IdempotencyService._prune_expired` |
| 7 | **Fragile observers** — an exception in a notifier (e.g. a webhook timeout) crashed the whole request, even though the money had already moved | Each observer call is wrapped and isolated; a failing notifier is logged, never propagated | `test_observer_isolation.py` |

If asked "what would you change to scale this to millions of users?" —
the in-memory `LockRegistry` becomes DB row locks (`SELECT ... FOR
UPDATE`) or a distributed lock (Redis Redlock), and the ledger would be
paginated/archived to cold storage instead of kept in a Python list.

## Reversals

`TransactionService.reverse(transaction_id, idempotency_key)` fully undoes
a previously `SUCCESS`ful transaction, fee included, and marks the
original `REVERSED`. Two details worth mentioning if asked:

- **The idempotency check runs before the status check.** A retried
  reversal request (same key) returns the original cached result instead
  of incorrectly failing with "already REVERSED" — the same class of bug
  as fix #3 above, just on a different code path.
- **A reversal can itself fail with `InsufficientBalanceError`** if the
  original receiver has already spent the money elsewhere. A real system
  would route that to manual/compliance review rather than pretend the
  reversal succeeded.

The locking logic that made `transfer()` safe (`_apply_wallet_deltas`) is
shared by `reverse()` — it takes a dict of `{wallet_id: signed_delta}` and
locks however many wallets are involved (2 or 3) in sorted order via a
single `ExitStack`, rather than being hard-coded to exactly two wallets.

### A bug found (and fixed) after the fact: concurrent double-reversal

The first version of `reverse()` read the original transaction's status,
then did the fund movement, then marked it `REVERSED` — a read-then-write
gap with nothing guarding it. Two reversal requests with *different*
idempotency keys (e.g. a user double-tapping "refund," or a client retry
that generated a fresh key instead of reusing the old one) could both read
`SUCCESS` before either had saved `REVERSED`, and both would proceed.

In testing, wallet-level locking made this look safe when the receiver's
balance happened to equal exactly the refund amount — the second attempt
failed with `InsufficientBalanceError` purely by chance, because the
wallet had already been drained to zero. Topping up the receiver with
unrelated funds first exposed the real bug: **10 concurrent reversal
requests all succeeded**, refunding the sender nine times over
(`tests/test_reversal_race.py` reproduces this against a deliberately
unfixed copy).

The fix adds a transaction-scoped lock (from the same `LockRegistry`,
keyed by a string namespaced so it can never collide with a wallet id)
around the read-check-claim sequence, and flips the original transaction
to `REVERSED` *before* moving any money rather than after — so a second
concurrent caller sees `REVERSED`, not `SUCCESS`, the instant it acquires
the lock. If the fund movement then fails, the claim is rolled back to
`SUCCESS` so the transaction's recorded status never lies about whether
money actually moved. Verified with the same break-it-then-fix-it method
used throughout this project, plus a mixed-load stress test that fires
concurrent transfers and reversals at the same overlapping wallets.

## A second round of review: what applied and what didn't

A second audit raised 8 more claims. Each was checked against the actual
code — not assumed correct — before anything was changed. Two turned out
to be real and severe; the rest either duplicated an already-fixed issue,
described an architecture this project doesn't use, or matched something
already correctly built and already tested.

| # | Claim | Verdict | Why |
|---|---|---|---|
| 1 | Observer exception after commit causes a false FAILED + released idempotency key, enabling double-debit | **Doesn't apply** | `_notify_observers` already runs *after* the transaction is marked SUCCESS and the idempotency key is completed, and wraps each observer in its own try/except — an observer's exception can't reach the outer handler. Already covered by `test_observer_isolation.py`. |
| 2 | Reversal locks wallets in semantic (receiver-then-sender) order, deadlocking against a concurrent forward transfer | **Doesn't apply** | `reverse()` builds the same kind of `{wallet_id: delta}` dict `transfer()` does and passes it to the same `_apply_wallet_deltas`, which always sorts by wallet_id regardless of caller. Verified with an adversarial probe: 40 concurrent forward transfers + 20 concurrent reversals on the same wallet pair, hard 5s timeout — 60/60 completed, 0 stuck. |
| 3 | No rollback across the wallet-mutation → ledger-write boundary; a mid-flight failure leaves balances mutated but the ledger incomplete | **Real, fixed** | Confirmed by mocking a ledger write to fail *after* wallet saves had already succeeded: money moved, transaction was marked FAILED, the idempotency key was released, and a client retry (correct behavior on their end) doubled the debit. Fixed by folding ledger writes and the SUCCESS status flip into the same `post_mutation` step that shares `_apply_wallet_deltas`'s rollback boundary, and by batching all of a transaction's ledger lines into one atomic `record_entries()` append so a multi-line write can't itself land partially. `tests/test_atomicity_regressions.py`. |
| 4 | Failed validation permanently poisons the idempotency key | **Already fixed** (original review, issue #3) | No change needed. |
| 5 | Reversal fee handling can either short the sender or create money from nothing | **Already correct** | `reverse()` already debits the revenue wallet by the fee and credits the sender `amount + fee` together, with matching ledger lines — verified by `test_reversing_a_fee_bearing_transfer_fully_restores_balances` asserting `ledger.is_balanced()`. |
| 6 | Striped/hashed lock pools can deadlock even when sorted by entity ID, if two entities share a hash bucket | **Doesn't apply** | `LockRegistry` isn't a striped pool — it's one dedicated `RLock` per wallet_id in an unbounded dict, so sorting by wallet_id directly is deadlock-safe by construction. (Worth naming honestly: that same unbounded dict never evicts, which is a real memory-growth question for a system with millions of distinct wallets over its lifetime — the same class of issue as #8 below, not the hash-collision deadlock described here.) |
| 7 | Unvalidated self-transfer (sender == receiver) causes double mutation or self-deadlock | **Real and severe, fixed** | Confirmed: `{sender_id: -X, receiver_id: +Y}` collapses to one dict key when sender == receiver, silently dropping the debit. A 300-unit "self-transfer" left the wallet **300 units richer**, while the ledger still reported itself balanced (it logs intended amounts, not actual deltas). Fixed with an explicit `SelfTransferError` guard at the top of `transfer()`, before anything else runs. `tests/test_atomicity_regressions.py`. |
| 8 | Ledger and transaction repository grow unbounded, same as the original idempotency-store issue | **Already acknowledged, not "fixed" by deletion** | Unlike idempotency records, ledger entries and transaction records are the audit trail itself — a real system archives them to cold storage, it doesn't delete them. This was already noted in the "scale to millions of users" line above; implementing full archival is out of scope for an in-memory demo and wouldn't be simulated correctly by just deleting rows. |

## A third finding, from re-auditing the code myself (no new document)

Asked to re-check the code without a new review document to work from, I
went looking for more of the same class of issue rather than assuming the
two prior rounds had caught everything. They hadn't.

**Reversing a reversal was allowed, and it lies in the transaction log.**
`reverse()` checked that the target transaction was `SUCCESS`, but nothing
stopped that target from *itself* being a reversal. Reproduced: transfer
₹200 from Alice to Bob, reverse it (Alice back to ₹1,000, `original` marked
`REVERSED`), then reverse *the reversal*. Money moved back to Bob exactly
as if the original transfer were back in effect — but both the original
transaction and its reversal still say `REVERSED`. Anyone reading the
transaction log afterward would wrongly conclude no transfer was active.

Fixed with a guard checked before the status check: `original.is_reversal`
is rejected outright, with a clear message that undoing a reversal means
issuing a new transfer, not reversing a reversal. `tests/test_reversal.py::test_reversing_a_reversal_is_rejected`.

## Known simplifications, disclosed rather than "fixed"

- **`WalletService.open_wallet(opening_balance=...)` bypasses the ledger
  entirely.** It's how every test in this project seeds a wallet with
  starting funds, but as a production API it would let anyone mint (or
  erase, via a negative value) balance with no audit trail. A real system
  would require initial funding to go through its own audited deposit
  operation, not a constructor argument. Left as-is here because it's
  test/demo scaffolding, not a path reachable through `transfer()` or
  `reverse()` — the two operations this project's guarantees are actually
  about.
- **`Wallet.currency` is never checked during a transfer.** Harmless today
  since everything here is INR, but would need enforcing before this
  design could honestly support multiple currencies.



