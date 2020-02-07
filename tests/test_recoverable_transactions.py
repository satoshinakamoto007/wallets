import asyncio
import pathlib
import tempfile
from decimal import Decimal
from aiter import map_aiter
from recoverable_wallet.recoverable_wallet import RecoverableWallet, InsufficientFundsError
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy, RemoteError
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from recoverable_wallet.recoverable_wallet_runnable import recovery_string_to_dict


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
    removals = [Coin.from_bytes(run(remote.hash_preimage(hash=x))) for x in removals_for_body(body)]

    for wallet in wallets:
        wallet.notify(additions, removals)

    return additions, removals


def test_standard_spend():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = RecoverableWallet(Decimal('1.1'), 1)
    wallet_b = RecoverableWallet(Decimal('1.1'), 1)
    farmer = RecoverableWallet(Decimal('1.1'), 1)
    wallets = [wallet_a, wallet_b, farmer]
    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert len(wallet_a.my_utxos) == 2
    assert wallet_b.current_balance == 0
    assert len(wallet_b.my_utxos) == 0
    # wallet a send to wallet b
    puzzlehash = wallet_b.get_new_puzzlehash()

    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    # give new wallet the reward to not complicate the one's we're tracking
    commit_and_notify(remote, wallets, farmer)

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert len(wallet_b.my_utxos) == 1

    # wallet b sends back to wallet a
    puzzlehash = wallet_a.get_new_puzzlehash()

    amount = 5000
    spend_bundle = wallet_b.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    # give new wallet the reward to not complicate the one's we're tracking
    commit_and_notify(remote, wallets, farmer)
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0


def test_recovery():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = RecoverableWallet(Decimal('1.1'), 1)
    wallet_b = RecoverableWallet(Decimal('1.1'), 1)
    farmer = RecoverableWallet(Decimal('1.1'), 1)
    wallets = [wallet_a, wallet_b, farmer]
    commit_and_notify(remote, wallets, wallet_a)
    commit_and_notify(remote, wallets, wallet_b)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000

    recovery_string = wallet_a.get_backup_string()
    recovery_dict = recovery_string_to_dict(recovery_string)
    root_public_key_serialized = recovery_dict['root_public_key'].serialize()
    recovery_pubkey = recovery_dict['root_public_key'].public_child(0).get_public_key().serialize()

    for coin in wallet_a.my_utxos.copy():
        pubkey = wallet_b.find_pubkey_for_hash(coin.puzzle_hash,
                                               root_public_key_serialized,
                                               recovery_dict['stake_factor'],
                                               recovery_dict['escrow_duration'])
        signed_transaction, destination_puzzlehash, amount = \
            wallet_b.generate_signed_recovery_to_escrow_transaction(coin,
                                                                    recovery_pubkey,
                                                                    pubkey,
                                                                    recovery_dict['stake_factor'],
                                                                    recovery_dict['escrow_duration'])
        child = Coin(coin.name(), destination_puzzlehash, amount)
        r = run(remote.push_tx(tx=signed_transaction))
        assert(type(r) is not RemoteError)
        wallet_b.escrow_coins[recovery_string].add(child)
        commit_and_notify(remote, wallets, farmer)
    assert wallet_a.current_balance == 0
    assert wallet_b.current_balance == 900000000
    commit_and_notify(remote, wallets, farmer)

    for recovery_string, coin_set in wallet_b.escrow_coins.items():
        recovery_dict = recovery_string_to_dict(recovery_string)
        root_public_key = recovery_dict['root_public_key']
        secret_key = recovery_dict['secret_key']
        escrow_duration = recovery_dict['escrow_duration']

        signed_transaction = wallet_b.generate_recovery_transaction(coin_set,
                                                                    root_public_key,
                                                                    secret_key,
                                                                    escrow_duration)
        r = run(remote.push_tx(tx=signed_transaction))
        assert type(r) is not RemoteError
    commit_and_notify(remote, wallets, farmer)
    assert wallet_a.current_balance == 0
    assert wallet_b.current_balance == 2000000000


def test_recovery_from_escrow_too_soon():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = RecoverableWallet(Decimal('1.1'), 1)
    wallet_b = RecoverableWallet(Decimal('1.1'), 1)
    farmer = RecoverableWallet(Decimal('1.1'), 1)
    wallets = [wallet_a, wallet_b, farmer]
    commit_and_notify(remote, wallets, wallet_a)
    commit_and_notify(remote, wallets, wallet_b)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000

    recovery_string = wallet_a.get_backup_string()
    recovery_dict = recovery_string_to_dict(recovery_string)
    root_public_key_serialized = recovery_dict['root_public_key'].serialize()
    recovery_pubkey = recovery_dict['root_public_key'].public_child(0).get_public_key().serialize()

    for coin in wallet_a.my_utxos.copy():
        pubkey = wallet_b.find_pubkey_for_hash(coin.puzzle_hash,
                                               root_public_key_serialized,
                                               recovery_dict['stake_factor'],
                                               recovery_dict['escrow_duration'])
        signed_transaction, destination_puzzlehash, amount = \
            wallet_b.generate_signed_recovery_to_escrow_transaction(coin,
                                                                    recovery_pubkey,
                                                                    pubkey,
                                                                    recovery_dict['stake_factor'],
                                                                    recovery_dict['escrow_duration'])
        child = Coin(coin.name(), destination_puzzlehash, amount)
        r = run(remote.push_tx(tx=signed_transaction))
        assert(type(r) is not RemoteError)
        wallet_b.escrow_coins[recovery_string].add(child)
        commit_and_notify(remote, wallets, farmer)
    assert wallet_a.current_balance == 0
    assert wallet_b.current_balance == 900000000

    for recovery_string, coin_set in wallet_b.escrow_coins.items():
        recovery_dict = recovery_string_to_dict(recovery_string)
        root_public_key = recovery_dict['root_public_key']
        secret_key = recovery_dict['secret_key']
        escrow_duration = recovery_dict['escrow_duration']

        signed_transaction = wallet_b.generate_recovery_transaction(coin_set,
                                                                    root_public_key,
                                                                    secret_key,
                                                                    escrow_duration)
        r = run(remote.push_tx(tx=signed_transaction))
        assert type(r) is RemoteError


def test_recovery_with_insufficient_funds():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = RecoverableWallet(Decimal('1.1'), 1)
    wallet_b = RecoverableWallet(Decimal('1.1'), 1)
    farmer = RecoverableWallet(Decimal('1.1'), 1)
    wallets = [wallet_a, wallet_b, farmer]
    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0

    recovery_string = wallet_a.get_backup_string()
    recovery_dict = recovery_string_to_dict(recovery_string)
    root_public_key_serialized = recovery_dict['root_public_key'].serialize()
    recovery_pubkey = recovery_dict['root_public_key'].public_child(0).get_public_key().serialize()

    import pytest
    with pytest.raises(InsufficientFundsError):
        for coin in wallet_a.my_utxos.copy():
            pubkey = wallet_b.find_pubkey_for_hash(coin.puzzle_hash,
                                                   root_public_key_serialized,
                                                   recovery_dict['stake_factor'],
                                                   recovery_dict['escrow_duration'])
            signed_transaction, destination_puzzlehash, amount = \
                wallet_b.generate_signed_recovery_to_escrow_transaction(coin,
                                                                        recovery_pubkey,
                                                                        pubkey,
                                                                        recovery_dict['stake_factor'],
                                                                        recovery_dict['escrow_duration'])
            r = run(remote.push_tx(tx=signed_transaction))
            assert(type(r) is not RemoteError)
            commit_and_notify(remote, wallets, farmer)


def test_clawback():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = RecoverableWallet(Decimal('1.1'), 1)
    wallet_b = RecoverableWallet(Decimal('1.1'), 1)
    farmer = RecoverableWallet(Decimal('1.1'), 1)
    wallets = [wallet_a, wallet_b, farmer]
    commit_and_notify(remote, wallets, wallet_a)
    commit_and_notify(remote, wallets, wallet_b)

    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000

    recovery_string = wallet_a.get_backup_string()
    recovery_dict = recovery_string_to_dict(recovery_string)
    root_public_key_serialized = recovery_dict['root_public_key'].serialize()
    recovery_pubkey = recovery_dict['root_public_key'].public_child(0).get_public_key().serialize()

    for coin in wallet_a.my_utxos.copy():
        pubkey = wallet_b.find_pubkey_for_hash(coin.puzzle_hash,
                                               root_public_key_serialized,
                                               recovery_dict['stake_factor'],
                                               recovery_dict['escrow_duration'])
        signed_transaction, destination_puzzlehash, amount = \
            wallet_b.generate_signed_recovery_to_escrow_transaction(coin,
                                                                    recovery_pubkey,
                                                                    pubkey,
                                                                    recovery_dict['stake_factor'],
                                                                    recovery_dict['escrow_duration'])
        r = run(remote.push_tx(tx=signed_transaction))
        assert(type(r) is not RemoteError)
    additions, deletions = commit_and_notify(remote, wallets, farmer)
    clawback_coins = [coin for coin in additions if wallet_a.is_in_escrow(coin)]
    assert len(clawback_coins) == 2
    assert wallet_a.current_balance == 0
    assert wallet_b.current_balance == 900000000
    transaction = wallet_a.generate_clawback_transaction(clawback_coins)
    r = run(remote.push_tx(tx=transaction))
    assert r is not RemoteError
    commit_and_notify(remote, wallets, farmer)
    assert wallet_a.current_balance == 1100000000
    assert wallet_b.current_balance == 900000000




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
