import asyncio
import pathlib
import tempfile
from aiter import map_aiter
from standard_wallet.wallet import Wallet
from custody_wallet.custody_wallet import CPWallet
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin, ProgramHash
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.atoms import hexbytes, uint64


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
    tip = run(remote.get_tip())
    index = int(tip["tip_index"])

    for wallet in wallets:
        if isinstance(wallet, CPWallet):
            spend_bundle = wallet.notify(additions, removals, index)
        else:
            spend_bundle = wallet.notify(additions, removals)
        if spend_bundle is not None:
            for bun in spend_bundle:
                _ = run(remote.push_tx(tx=bun))


def test_cp_receive():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CPWallet()
    wallet_b = CPWallet()
    wallet_c = CPWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    pub_a = hexbytes(wallet_a.get_next_public_key().serialize())
    pub_b = hexbytes(wallet_b.get_next_public_key().serialize())
    wallet_b.pubkey_permission = pub_a
    wallet_b.unlock_time = 100
    b_puzzle = wallet_b.cp_puzzle(pub_b, pub_a, 100)
    b_puzzlehash = ProgramHash(b_puzzle)


    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0
    assert wallet_c.current_balance == 0

    spend_bundle = wallet_a.generate_signed_transaction(1000, b_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0


def test_cp_send_solo():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CPWallet()
    wallet_b = CPWallet()
    wallet_c = CPWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    pub_a = hexbytes(wallet_a.get_next_public_key().serialize())
    pub_b = hexbytes(wallet_b.get_next_public_key().serialize())
    wallet_b.pubkey_permission = pub_a
    wallet_b.unlock_time = 3
    b_puzzle = wallet_b.cp_puzzle(pub_b, pub_a, 3)
    b_puzzlehash = ProgramHash(b_puzzle)

    # Set ledger api to
    _ = run(remote.skip_milliseconds(ms=uint64(4).to_bytes(4, 'big')))

    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0
    assert wallet_c.current_balance == 0

    spend_bundle = wallet_a.generate_signed_transaction(1000, b_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0



    puzzlehash_c = wallet_c.get_new_puzzlehash()
    spend_bundle = wallet_b.cp_generate_signed_transaction(puzzlehash_c, 100)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 900
    assert wallet_c.current_balance == 100


def test_cp_send_solo_fail():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CPWallet()
    wallet_b = CPWallet()
    wallet_c = CPWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    pub_a = hexbytes(wallet_a.get_next_public_key().serialize())
    pub_b = hexbytes(wallet_b.get_next_public_key().serialize())
    wallet_b.pubkey_permission = pub_a
    wallet_b.unlock_time = 3
    b_puzzle = wallet_b.cp_puzzle(pub_b, pub_a, 3)
    b_puzzlehash = ProgramHash(b_puzzle)

    # Set time to 2, time needs to be greater than 3 in order to be valid
    _ = run(remote.skip_milliseconds(ms=uint64(2).to_bytes(4, 'big')))
    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0
    assert wallet_c.current_balance == 0

    spend_bundle = wallet_a.generate_signed_transaction(1000, b_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0

    puzzlehash_c = wallet_c.get_new_puzzlehash()
    spend_bundle = wallet_b.cp_generate_signed_transaction(puzzlehash_c, 100)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0


def test_cp_with_permission():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CPWallet()
    wallet_b = CPWallet()
    wallet_c = CPWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    pub_a = hexbytes(wallet_a.get_next_public_key().serialize())
    pub_b = hexbytes(wallet_b.get_next_public_key().serialize())
    unlock_time = 5
    wallet_b.pubkey_permission = pub_a
    wallet_b.unlock_time = unlock_time
    wallet_a.pubkey_approval = pub_a
    b_puzzle = wallet_b.cp_puzzle(pub_b, pub_a, unlock_time)
    b_puzzlehash = ProgramHash(b_puzzle)

    commit_and_notify(remote, wallets, wallet_a)
    # Set time to 4, time needs to exceed 5, unless there is approval from authorizer
    _ = run(remote.skip_milliseconds(ms=uint64(4).to_bytes(4, 'big')))

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0
    assert wallet_c.current_balance == 0

    spend_bundle = wallet_a.generate_signed_transaction(1000, b_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0

    puzzlehash_c = wallet_c.get_new_puzzlehash()
    amount = 100
    mode = 2
    transaction = wallet_b.cp_generate_unsigned_transaction(puzzlehash_c, amount, mode)
    solution = transaction[0][1].solution
    approval_a = wallet_a.cp_approval_signature_for_transaction(solution).sig
    spend_bundle = wallet_b.cp_generate_signed_transaction_with_approval(puzzlehash_c, amount, approval_a)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 900
    assert wallet_c.current_balance == 100


def test_cp_without_permission():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CPWallet()
    wallet_b = CPWallet()
    wallet_c = CPWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    pub_a = hexbytes(wallet_a.get_next_public_key().serialize())
    pub_b = hexbytes(wallet_b.get_next_public_key().serialize())
    unlock_time = 5
    wallet_b.pubkey_permission = pub_a
    wallet_b.unlock_time = unlock_time
    wallet_a.pubkey_approval = pub_a
    b_puzzle = wallet_b.cp_puzzle(pub_b, pub_a, unlock_time)
    b_puzzlehash = ProgramHash(b_puzzle)

    commit_and_notify(remote, wallets, wallet_a)
    # Set time to 4, time needs to exceed 5, unless there is approval from authorizer
    _ = run(remote.skip_milliseconds(ms=uint64(4).to_bytes(4, 'big')))

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0
    assert wallet_c.current_balance == 0

    spend_bundle = wallet_a.generate_signed_transaction(1000, b_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0

    puzzlehash_c = wallet_c.get_new_puzzlehash()
    amount = 100
    mode = 2
    transaction = wallet_b.cp_generate_unsigned_transaction(puzzlehash_c, amount, mode)
    spend_bundle = wallet_b.cp_generate_signed_transaction_with_approval(puzzlehash_c, amount, None)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999000
    assert wallet_b.cp_balance == 1000
    assert wallet_c.current_balance == 0

"""
Copyright 2018 Chia Network Inc
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""