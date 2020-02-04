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

    # Wallet A generates some genesis coins to itself.
    amount = 10000
    my_utxos_copy = wallet_a.temp_utxos.copy()
    genesisCoin = my_utxos_copy.pop()
    while genesisCoin.amount < amount and len(my_utxos_copy) > 0:
        genesisCoin = my_utxos_copy.pop()
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins([amount], genesisCoin=genesisCoin)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert len(wallet_a.my_coloured_coins) == 1

    # Wallet A does Eve spend to itself
    innersol = binutils.assemble("()")

    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert coin.parent_coin_info == genesisCoin.name()
    core = wallet_a.my_coloured_coins[coin][1]
    wallet_b.cc_add_core(core)
    assert ProgramHash(clvm.to_sexp_f(wallet_a.cc_make_puzzle(ProgramHash(wallet_a.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    # parent info is origin ID
    parent_info = genesisCoin.name()

    # don't need sigs for eve spend
    sigs = []

    spend_bundle = wallet_a.cc_generate_eve_spend([(coin, parent_info, amount, innersol)])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1
    assert coin not in wallet_a.my_coloured_coins


    # Generate spend so that Wallet B can receive the coin

    newinnerpuzhash = wallet_b.get_new_puzzlehash()  # these are irrelevant because eve spend doesn't run innerpuz
    innersol = make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    # parent info update
    innerpuzhash = ProgramHash(wallet_a.my_coloured_coins[list(wallet_a.my_coloured_coins.keys()).copy().pop()][0])  # have you ever seen something so disgusting
    parent_info = (coin.parent_coin_info, innerpuzhash, coin.amount)
    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert ProgramHash(clvm.to_sexp_f(wallet_a.cc_make_puzzle(ProgramHash(wallet_a.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    # Generate signatures for inner standard spend
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coin][0], innersol)

    assert sigs != []
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list([(coin, parent_info, amount, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 1
    assert len(wallet_a.my_coloured_coins) == 0

    # wallet B spends coloured coin back to wallet A
    parent_info = (coin.parent_coin_info, innerpuzhash, coin.amount)
    pubkey, secretkey = wallet_b.get_keys(newinnerpuzhash)
    innerpuzhash = newinnerpuzhash
    newinnerpuzhash = wallet_a.get_new_puzzlehash()
    innersol = make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    coin = list(wallet_b.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert ProgramHash(clvm.to_sexp_f(wallet_b.cc_make_puzzle(ProgramHash(wallet_b.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[coin][0], innersol)

    assert sigs != []
    spend_bundle = wallet_b.cc_generate_spends_for_coin_list([(coin, parent_info, amount, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1


def test_multiple_cc_spends_once():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates some genesis coins to itself.
    amounts = [10000, 500, 1000]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 3
    assert wallet_a.current_balance == 999988500

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    core = wallet_a.my_coloured_coins[coins[0]][1]
    wallet_b.cc_add_core(core)

    # Eve spend coins
    parent_info = coins[0].parent_coin_info

    # don't need sigs or a proper innersol for eve spend
    spendlist = []
    innersol = binutils.assemble("()")
    for coin in coins:
        spendlist.append((coin, parent_info, coin.amount, innersol))
    spend_bundle = wallet_a.cc_generate_eve_spend(spendlist)
    _ = run(remote.push_tx(tx=spend_bundle))

    # update parent info before the information is lost
    parent_info = dict()  # (coin.parent_coin_info, innerpuzhash, coin.amount)
    for coin in coins:
        parent_info[coin.name()] = (coin.parent_coin_info, ProgramHash(wallet_a.my_coloured_coins[coin][0]), coin.amount)

    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 3
    assert wallet_a.current_balance == 999988500



    # Send 1500 chia to Wallet B
    spendslist = []  # spendslist is [(coin, parent_info, amount, innersol)]

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    for coin in coins:
        if coin.amount == 10000:
            coins.remove(coin)
            continue
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': 1500}])
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coins[0]][0], innersol)
    spendslist.append((coins[0], parent_info[coins[0].parent_coin_info], 1500, innersol))
    innersol = binutils.assemble("(q ())")
    sigs = sigs + wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coins[1]][0], innersol)
    spendslist.append((coins[1], parent_info[coins[1].parent_coin_info], 0, innersol))

    spend_bundle = wallet_a.cc_generate_spends_for_coin_list(spendslist, sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    #breakpoint()
    assert len(wallet_a.my_coloured_coins) == 1
    assert len(wallet_b.my_coloured_coins) == 1
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1500
