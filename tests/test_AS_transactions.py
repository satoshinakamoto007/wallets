import asyncio
import pathlib
import tempfile
import os
from aiter import map_aiter
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from atomic_swaps.as_wallet import ASWallet


async def proxy_for_unix_connection(path):
    reader, writer = await asyncio.open_unix_connection(path)
    return request_response_proxy(reader, writer, ledger_sim.REMOTE_SIGNATURES)


def create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, a, b, amount_a, amount_b, a_pubkey, b_pubkey):
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = wallets[a]
    wallet_b = wallets[b]
    as_swap_list_a = as_list_list[a]
    as_swap_list_b = as_list_list[b]
    # Setup for A
    secret = os.urandom(256).hex()
    secret_hash = wallet_a.as_generate_secret_hash(secret)
    tip = run(remote.get_tip())
    timelock_a = 10
    timelock_block_a = int(timelock_a + tip["tip_index"])
    puzzlehash_a = wallet_a.as_get_new_puzzlehash(bytes(a_pubkey), bytes(b_pubkey), amount_a, timelock_block_a, secret_hash)
    spend_bundle_a = wallet_a.generate_signed_transaction(amount_a, puzzlehash_a)

    puzzlehash_b = "unknown"
    timelock_b = int(0.5 * timelock_a)
    timelock_block_b = "unknown"
    new_swap = {
            "swap partner": "wallet_b",
            "partner pubkey": b_pubkey,
            "amount_outgoing" : amount_a,
            "amount_incoming" : amount_b,
            "secret": secret,
            "secret hash": secret_hash,
            "my swap pubkey": a_pubkey,
            "outgoing puzzlehash": puzzlehash_a.hex(),
            "timelock time outgoing": timelock_a,
            "timelock block height outgoing": timelock_block_a,
            "incoming puzzlehash": puzzlehash_b,
            "timelock time incoming": timelock_b,
            "timelock block height incoming": timelock_block_b
    }
    as_swap_list_a.append(new_swap)

    # Setup for B
    tip = run(remote.get_tip())
    timelock_block_b = int(timelock_b + tip["tip_index"])
    puzzlehash_b = wallet_b.as_get_new_puzzlehash(bytes(b_pubkey), bytes(a_pubkey), amount_b, timelock_block_b, secret_hash)
    spend_bundle_b = wallet_b.generate_signed_transaction(amount_b, puzzlehash_b)
    secret = "unknown"

    assert puzzlehash_b != puzzlehash_a

    new_swap = {
            "swap partner": "wallet_a",
            "partner pubkey": a_pubkey,
            "amount_outgoing" : amount_b,
            "amount_incoming" : amount_a,
            "secret": secret,
            "secret hash": secret_hash,
            "my swap pubkey": b_pubkey,
            "outgoing puzzlehash": puzzlehash_b.hex(),
            "timelock time outgoing": timelock_b,
            "timelock block height outgoing": timelock_block_b,
            "incoming puzzlehash": puzzlehash_a.hex(),
            "timelock time incoming": timelock_a,
            "timelock block height incoming": timelock_block_a
    }
    as_swap_list_b.append(new_swap)

    # Finish information for wallet_a
    as_swap_list_a[len(as_swap_list_a)-1]["incoming puzzlehash"] = puzzlehash_b.hex()
    as_swap_list_a[len(as_swap_list_a)-1]["timelock block height incoming"] = timelock_block_b
    return spend_bundle_a, spend_bundle_b


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


def commit_and_notify(remote, wallets, reward_recipient, as_list_list):
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
    i = 0
    for wallet in wallets:
        if isinstance(wallet, ASWallet):
            spend_bundle = wallet.notify(additions, removals)
        else:
            spend_bundle = wallet.notify(additions, removals)
        if spend_bundle is not None:
            for bun in spend_bundle:
                _ = run(remote.push_tx(tx=bun))
        if as_list_list[i] != []:
            wallet.pull_preimage(body, removals)
        i = i + 1


def test_AS_standardcase():
    # Setup
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = ASWallet()
    wallet_b = ASWallet()
    wallets = [wallet_a, wallet_b]
    as_swap_list_a = wallet_a.as_swap_list
    as_swap_list_b = wallet_b.as_swap_list
    as_list_list = [as_swap_list_a, as_swap_list_b]

    # Give money to both wallets
    commit_and_notify(remote, wallets, wallet_a, as_list_list)
    commit_and_notify(remote, wallets, wallet_b, as_list_list)
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000
    a_pubkey = wallet_a.get_next_public_key()
    b_pubkey = wallet_b.get_next_public_key()

    # Start swap logic
    amount_a = 1000
    amount_b = 5000

    spend_bundle_a, spend_bundle_b = create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, 0, 1, amount_a, amount_b, a_pubkey, b_pubkey)
    # Commit B's transaction
    _ = run(remote.push_tx(tx=spend_bundle_a))
    _ = run(remote.push_tx(tx=spend_bundle_b))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    assert wallet_a.current_balance == 999999000
    assert wallet_b.current_balance == 999995000
    assert len(wallet_a.as_pending_utxos) == 2
    assert len(wallet_b.as_pending_utxos) == 2
    assert as_swap_list_b[0]["secret"] == "unknown"

    # Wallet A claim swap
    swap = as_swap_list_a[0]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 1000004000
    assert wallet_b.current_balance == 999995000
    assert as_swap_list_b[0]["secret"] == as_swap_list_a[0]["secret"]

    # Wallet B claim swap
    swap = as_swap_list_b[0]
    spend_bundle = wallet_b.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 1000004000
    assert wallet_b.current_balance == 999996000


def test_as_claim_back():
    # Setup
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = ASWallet()
    wallet_b = ASWallet()
    wallets = [wallet_a, wallet_b]
    as_swap_list_a = wallet_a.as_swap_list
    as_swap_list_b = wallet_b.as_swap_list
    as_list_list = [as_swap_list_a, as_swap_list_b]

    # Give money to both wallets
    commit_and_notify(remote, wallets, wallet_a, as_list_list)
    commit_and_notify(remote, wallets, wallet_b, as_list_list)
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000
    a_pubkey = wallet_a.get_next_public_key()
    b_pubkey = wallet_b.get_next_public_key()

    # Start swap logic
    amount_a = 1000
    amount_b = 5000

    spend_bundle_a, spend_bundle_b = create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, 0, 1, amount_a, amount_b, a_pubkey, b_pubkey)
    # Commit B's transaction
    _ = run(remote.push_tx(tx=spend_bundle_a))
    _ = run(remote.push_tx(tx=spend_bundle_b))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    assert wallet_a.current_balance == 999999000
    assert wallet_b.current_balance == 999995000
    assert len(wallet_a.as_pending_utxos) == 2
    assert len(wallet_b.as_pending_utxos) == 2

    # Wallet A tries to claim their own coin before waiting period has passed
    swap = as_swap_list_a[0]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["outgoing puzzlehash"], swap["amount_outgoing"], int(swap["timelock block height outgoing"]), swap["secret hash"], as_pubkey_sender = bytes(swap["my swap pubkey"]), as_pubkey_receiver = bytes(swap["partner pubkey"]), who = "sender", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999999000  # no new money
    assert wallet_b.current_balance == 999995000

    # Wait 6 blocks
    for i in range(6):
        commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    # Wallet B should be able to claim back at this point and Wallet A should not be able to
    swap = as_swap_list_a[0]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["outgoing puzzlehash"], swap["amount_outgoing"], int(swap["timelock block height outgoing"]), swap["secret hash"], as_pubkey_sender = bytes(swap["my swap pubkey"]), as_pubkey_receiver = bytes(swap["partner pubkey"]), who = "sender", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    swap = as_swap_list_b[0]
    spend_bundle = wallet_b.as_create_spend_bundle(swap["outgoing puzzlehash"], swap["amount_outgoing"], int(swap["timelock block height outgoing"]), swap["secret hash"], as_pubkey_sender = bytes(swap["my swap pubkey"]), as_pubkey_receiver = bytes(swap["partner pubkey"]), who = "sender", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999999000
    assert wallet_b.current_balance == 1000000000

    # Some time passes
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    # Wallet A tries to claim their own coin
    swap = as_swap_list_a[0]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["outgoing puzzlehash"], swap["amount_outgoing"], int(swap["timelock block height outgoing"]), swap["secret hash"], as_pubkey_sender = bytes(swap["my swap pubkey"]), as_pubkey_receiver = bytes(swap["partner pubkey"]), who = "sender", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_b.current_balance == 1000000000
    assert wallet_a.current_balance == 1000000000


def test_multiple_concurrent_swaps():
    # Setup
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = ASWallet()
    wallet_b = ASWallet()
    wallet_c = ASWallet()
    wallets = [wallet_a, wallet_b, wallet_c]
    as_swap_list_a = wallet_a.as_swap_list
    as_swap_list_b = wallet_b.as_swap_list
    as_swap_list_c = wallet_c.as_swap_list
    as_list_list = [as_swap_list_a, as_swap_list_b, as_swap_list_c]

    # Give money to all wallets
    commit_and_notify(remote, wallets, wallet_a, as_list_list)
    commit_and_notify(remote, wallets, wallet_b, as_list_list)
    commit_and_notify(remote, wallets, wallet_c, as_list_list)
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000
    assert wallet_b.current_balance == 1000000000

    a_pubkey = wallet_a.get_next_public_key()
    b_pubkey = wallet_b.get_next_public_key()
    c_pubkey = wallet_c.get_next_public_key()

    # Start swap logic
    amount_a_to_b = 100
    amount_b_to_a = 200
    amount_b_to_c = 3000
    amount_c_to_b = 4000
    amount_c_to_a = 50000
    amount_a_to_c = 60000

    # Setup for AB swap
    spend_bundle_a, spend_bundle_b = create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, 0, 1, amount_a_to_b, amount_b_to_a, a_pubkey, b_pubkey)
    # Commit transactions
    _ = run(remote.push_tx(tx=spend_bundle_a))
    _ = run(remote.push_tx(tx=spend_bundle_b))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    assert wallet_a.current_balance == 999999900
    assert wallet_b.current_balance == 999999800
    assert wallet_c.current_balance == 1000000000
    assert len(wallet_a.as_pending_utxos) == 2
    assert len(wallet_b.as_pending_utxos) == 2
    assert len(wallet_c.as_pending_utxos) == 0

    # Setup for BC swap
    spend_bundle_a, spend_bundle_b = create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, 1, 2, amount_b_to_c, amount_c_to_b, b_pubkey, c_pubkey)
    # Commit transactions
    _ = run(remote.push_tx(tx=spend_bundle_a))
    _ = run(remote.push_tx(tx=spend_bundle_b))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    assert wallet_a.current_balance == 999999900
    assert wallet_b.current_balance == 999996800
    assert wallet_c.current_balance == 999996000
    assert len(wallet_a.as_pending_utxos) == 2
    assert len(wallet_b.as_pending_utxos) == 4
    assert len(wallet_c.as_pending_utxos) == 2

    # Setup for CA swap
    spend_bundle_a, spend_bundle_b = create_swap_for_two_wallet_numbers(remote, wallets, as_list_list, 2, 0, amount_c_to_a, amount_a_to_c, c_pubkey, a_pubkey)
    # Commit transactions
    _ = run(remote.push_tx(tx=spend_bundle_a))
    _ = run(remote.push_tx(tx=spend_bundle_b))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)

    assert wallet_a.current_balance == 999939900
    assert wallet_b.current_balance == 999996800
    assert wallet_c.current_balance == 999946000
    assert len(wallet_a.as_pending_utxos) == 4
    assert len(wallet_b.as_pending_utxos) == 4
    assert len(wallet_c.as_pending_utxos) == 4

    # Order will be - B claims BC, C claims CA, C claims BC, A claims AB, B claims AB, A claims CA

    # Wallet B claim swap BC
    swap = as_swap_list_b[1]
    spend_bundle = wallet_b.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999939900
    assert wallet_b.current_balance == 1000000800
    assert wallet_c.current_balance == 999946000
    assert as_swap_list_c[0]["secret"] == as_swap_list_b[1]["secret"]

    # Wallet C claim swap CA
    swap = as_swap_list_c[1]
    spend_bundle = wallet_c.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999939900
    assert wallet_b.current_balance == 1000000800
    assert wallet_c.current_balance == 1000006000
    assert as_swap_list_a[1]["secret"] == as_swap_list_c[1]["secret"]

    # Wallet C claim swap BC
    swap = as_swap_list_c[0]
    spend_bundle = wallet_c.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    # Wallet A claim swap AB
    swap = as_swap_list_a[0]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999940100
    assert wallet_b.current_balance == 1000000800
    assert wallet_c.current_balance == 1000009000
    assert as_swap_list_a[0]["secret"] == as_swap_list_b[0]["secret"]

    # Wallet B claim swap AB
    swap = as_swap_list_b[0]
    spend_bundle = wallet_b.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    # Wallet A claim swap CA
    swap = as_swap_list_a[1]
    spend_bundle = wallet_a.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount_incoming"], int(swap["timelock block height incoming"]), swap["secret hash"], as_pubkey_sender = bytes(swap["partner pubkey"]), as_pubkey_receiver = bytes(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, ASWallet(), as_list_list)
    assert wallet_a.current_balance == 999990100
    assert wallet_b.current_balance == 1000000900
    assert wallet_c.current_balance == 1000009000
