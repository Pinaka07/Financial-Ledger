from tests.helpers import build_system


def test_open_wallet_and_get_balance():
    system = build_system()
    wallet_service = system["wallet_service"]

    wallet = wallet_service.open_wallet(owner_id="alice", opening_balance=500)

    assert wallet_service.get_balance(wallet.id) == 500


def test_topup_increases_balance():
    system = build_system()
    wallet_service = system["wallet_service"]

    wallet = wallet_service.open_wallet(owner_id="alice", opening_balance=100)
    wallet_service.topup(wallet.id, 50)

    assert wallet_service.get_balance(wallet.id) == 150
