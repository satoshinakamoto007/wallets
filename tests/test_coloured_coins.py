import asyncio
import pathlib
import tempfile
from aiter import map_aiter
from coloured_coins.cc_wallet import CCWallet
from standard_wallet.wallet import Wallet
from authorised_payees import ap_wallet_a_functions
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin
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
        wallet.notify(additions, removals)


def test_cc_standard():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    # A gives some unique coloured Chia coins to B who is then able to spend it while retaining the colouration
    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet B generates some genesis coins to itself.
    innerpuz = wallet_a.get_new_puzzlehash()

    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(10000, innerpuz)
    _ = run(remote.push_tx(tx=spend_bundle))
    # commit_and_notify(remote, wallets, Wallet())
    # manually commit and notify so we can run assert on additions

    coinbase_puzzle_hash = Wallet().get_new_puzzlehash()
    fees_puzzle_hash = Wallet().get_new_puzzlehash()
    r = run(remote.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash,
                                fees_puzzle_hash=fees_puzzle_hash))
    body = r.get("body")

    additions = list(additions_for_body(body))
    add_cop = additions.copy()
    assert len(additions) == 4
    inspector = add_cop.pop()
    while inspector.amount != 10000 and len(add_cop) > 0:
        inspector = add_cop.pop()
    assert wallet_a.cc_can_generate(inspector.puzzle_hash)

    removals = removals_for_body(body)
    removals = [Coin.from_bytes(run(remote.hash_preimage(hash=x)))
                              for x in removals]

    for wallet in wallets:
        wallet.notify(additions, removals)
