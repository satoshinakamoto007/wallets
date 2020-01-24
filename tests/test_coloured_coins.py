import asyncio
import pathlib
import tempfile
import clvm
from aiter import map_aiter
from coloured_coins.cc_wallet import CCWallet
from standard_wallet.wallet import Wallet, make_solution
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin, Program, ProgramHash
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.validation.Conditions import conditions_by_opcode
from chiasim.validation.consensus import (
    conditions_for_solution, hash_key_pairs_for_conditions_dict
)
from clvm_tools import binutils


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
    innerpuzhash = wallet_a.get_new_puzzlehash()
    amount = 10000
    my_utxos_copy = wallet_a.temp_utxos.copy()
    genesisCoin = my_utxos_copy.pop()
    while genesisCoin.amount < amount and len(my_utxos_copy) > 0:
        genesisCoin = my_utxos_copy.pop()
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amount, innerpuzhash, genesisCoin=genesisCoin)
    _ = run(remote.push_tx(tx=spend_bundle))
    # manually commit and notify so we can run assert on additions

    coinbase_puzzle_hash = Wallet().get_new_puzzlehash()
    fees_puzzle_hash = Wallet().get_new_puzzlehash()
    r = run(remote.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash,
                                fees_puzzle_hash=fees_puzzle_hash))
    body = r.get("body")

    additions = list(additions_for_body(body))
    add_copy = additions.copy()
    assert len(additions) == 4
    inspector = add_copy.pop()
    while inspector.amount != 10000 and len(add_copy) > 0:
        inspector = add_copy.pop()
    assert wallet_a.cc_can_generate(inspector.puzzle_hash)

    removals = removals_for_body(body)
    removals = [Coin.from_bytes(run(remote.hash_preimage(hash=x)))for x in removals]

    for wallet in wallets:
        wallet.notify(additions, removals)

    assert len(wallet_a.my_coloured_coins) == 1

    # Generate spend so that Wallet B can receive the coin

    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    # need to have the aggsigs for the standard puzzle in innerpuz

    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert inspector == coin
    assert coin.parent_coin_info == genesisCoin.name()
    core = wallet_a.my_coloured_coins[coin][1]
    wallet_b.cc_add_core(core)
    assert ProgramHash(clvm.to_sexp_f(wallet_a.cc_make_puzzle(ProgramHash(wallet_a.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    sigs = []
    pubkey, secretkey = wallet_a.get_keys(innerpuzhash)
    secretkey = BLSPrivateKey(secretkey)
    code_ = [puzzle_for_pk(pubkey.serialize()), [innersol, []]]
    sexp = clvm.to_sexp_f(code_)
    conditions_dict = conditions_by_opcode(
        conditions_for_solution(sexp))
    for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
        signature = secretkey.sign(_.message_hash)
        sigs.append(signature)

    assert sigs != []

    # parent info is origin ID
    parent_info = genesisCoin.name()

    spend_bundle = wallet_a.cc_generate_signed_transaction(coin, parent_info, amount, innersol, sigs=sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 1
    assert len(wallet_a.my_coloured_coins) == 0



    # wallet B spends coloured coin back to wallet A
    parent_info = (coin.parent_coin_info, innerpuzhash, coin.amount)
    pubkey, secretkey = wallet_b.get_keys(newinnerpuzhash)
    newinnerpuzhash = wallet_a.get_new_puzzlehash()
    innersol = make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    coin = list(wallet_b.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert ProgramHash(clvm.to_sexp_f(wallet_b.cc_make_puzzle(ProgramHash(wallet_b.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash
    print(f"DEBUG puzstring 2: {binutils.disassemble(clvm.to_sexp_f(wallet_b.cc_make_puzzle(ProgramHash(wallet_b.my_coloured_coins[coin][0]), core)))}")
    sigs = []
    secretkey = BLSPrivateKey(secretkey)
    code_ = [puzzle_for_pk(pubkey.serialize()), [innersol, []]]
    sexp = clvm.to_sexp_f(code_)
    conditions_dict = conditions_by_opcode(
        conditions_for_solution(sexp))
    for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
        signature = secretkey.sign(_.message_hash)
        sigs.append(signature)

    assert sigs != []
    breakpoint()
    spend_bundle = wallet_b.cc_generate_signed_transaction(coin, parent_info, amount, innersol, sigs=sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1
