import asyncio
import pathlib
import tempfile
from aiter import map_aiter
from ..wallet.wallet import Wallet
from ..wallet.rl_wallet import RLWallet
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin, ProgramHash
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body


async def proxy_for_unix_connection(path):
    reader, writer = await asyncio.open_unix_connection(path)
    return request_response_proxy(reader, writer, ledger_sim.REMOTE_SIGNATURES)


def make_client_server():
    init_logging()
    run = asyncio.get_event_loop().run_until_complete
    path = pathlib.Path(tempfile.mkdtemp(), "port")
    server, aiter = run(start_unix_server_aiter(path))
    rws_aiter = map_aiter(lambda rw: dict(
        reader=rw[0], writer=rw[1], server=server), aiter)
    initial_block_hash = bytes(([0] * 31) + [1])
    ledger = ledger_api.LedgerAPI(initial_block_hash, RAM_DB())
    server_task = asyncio.ensure_future(api_server(rws_aiter, ledger))
    remote = run(proxy_for_unix_connection(path))
    # make sure server_task isn't garbage collected
    remote.server_task = server_task
    return remote


def commit_and_notify(remote, wallets, reward_recipient):
    run = asyncio.get_event_loop().run_until_complete
    coinbase_puzzle_hash = reward_recipient.get_new_puzzlehash()
    fees_puzzle_hash = reward_recipient.get_new_puzzlehash()
    r = run(remote.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash,
                              fees_puzzle_hash=fees_puzzle_hash))
    body = r.get("body")

    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(run(remote.hash_preimage(hash=x)))
                for x in removals]

    for wallet in wallets:
        spend_bundle = wallet.notify(additions, removals)
        if spend_bundle is not None:
            for bun in spend_bundle:
                _ = run(remote.push_tx(tx=bun))


def test_RL_spend():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = Wallet()
    wallet_b = RLWallet()
    wallet_c = Wallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    wallet_b_pk = wallet_b.get_next_public_key().serialize()


    #give coinbase reward to  wallet_a (1000000000)
    commit_and_notify(remote, wallets, wallet_a)
    assert wallet_a.current_balance == 1000000000

    wallet_a_coinbase_coin = wallet_a.my_utxos.copy().pop()
    wallet_a_coinbase_coin = wallet_a.my_utxos.copy().pop()

    wacc_name = wallet_a_coinbase_coin.name()
    #wallet A is normal wallet, it sends coin that's rate limited to wallet B
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, 10, 1, wacc_name)
    wallet_b.setOrigin(wallet_a_coinbase_coin)
    wallet_b.limit = 10
    wallet_b.interval = 1
    rl_puzzlehash = ProgramHash(rl_puzzle)

    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, rl_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert wallet_c.current_balance == 0

    #Now send some coins from b to c
    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())

    amount = 10
    wallet_c_puzzlehash = wallet_c.get_new_puzzlehash()
    spend_bundle = wallet_b.rl_generate_signed_transaction(wallet_c_puzzlehash, amount)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 4990
    assert wallet_c.current_balance == 10

    amount = 10
    wallet_c_puzzlehash = wallet_c.get_new_puzzlehash()
    spend_bundle = wallet_b.rl_generate_signed_transaction(wallet_c_puzzlehash, amount)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 4980
    assert wallet_c.current_balance == 20

    #Test Aggregation
    #A wants to send more chia to same rate limited wallet
    aggregation_puzzlehash = wallet_b.rl_get_aggregation_puzzlehash(rl_puzzlehash)
    spend_bundle = wallet_a.generate_signed_transaction(5000, aggregation_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    #First commit sends coin to aggregation puzzle
    commit_and_notify(remote, wallets, Wallet())
    #Second consolidates aggregation coin and RL Coin
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999990000
    assert wallet_b.current_balance == 9980
    assert wallet_c.current_balance == 20

    commit_and_notify(remote, wallets, Wallet())
    amount = 10
    wallet_c_puzzlehash = wallet_c.get_new_puzzlehash()
    spend_bundle = wallet_b.rl_generate_signed_transaction(wallet_c_puzzlehash, amount)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999990000
    assert wallet_b.current_balance == 9970
    assert wallet_c.current_balance == 30



