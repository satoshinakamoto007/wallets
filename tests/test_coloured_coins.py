import asyncio
import pathlib
import tempfile
import clvm
from aiter import map_aiter
from coloured_coins.cc_wallet import CCWallet
from standard_wallet.wallet import Wallet
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
        if isinstance(wallet, CCWallet):
            wallet.notify(additions, removals, body)
        else:
            wallet.notify(additions, removals)


def test_cc_single():
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
    #parent_info = genesisCoin.name()

    # don't need sigs for eve spend
    sigs = []

    spend_bundle = wallet_a.cc_generate_eve_spend([(coin, wallet_a.parent_info[coin.parent_coin_info], amount, innersol)])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1
    assert coin not in wallet_a.my_coloured_coins

    # Generate spend so that Wallet B can receive the coin
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    # parent info update
    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert ProgramHash(clvm.to_sexp_f(wallet_a.cc_make_puzzle(ProgramHash(wallet_a.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    # Generate signatures for inner standard spend
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coin][0], innersol)

    assert sigs != []
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list([(coin, wallet_a.parent_info[coin.parent_coin_info], amount, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 1
    assert len(wallet_a.my_coloured_coins) == 0

    # wallet B spends coloured coin back to wallet A
    #parent_info = (coin.parent_coin_info, innerpuzhash, coin.amount)
    pubkey, secretkey = wallet_b.get_keys(newinnerpuzhash)
    newinnerpuzhash = wallet_a.get_new_puzzlehash()
    innersol = wallet_a.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount}])

    coin = list(wallet_b.my_coloured_coins.keys()).copy().pop()  # this is a hack - design things properly
    assert ProgramHash(clvm.to_sexp_f(wallet_b.cc_make_puzzle(ProgramHash(wallet_b.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash

    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[coin][0], innersol)

    assert sigs != []
    spend_bundle = wallet_b.cc_generate_spends_for_coin_list([(coin, wallet_b.parent_info[coin.parent_coin_info], amount, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1


def test_audit_coloured_coins():
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
    #parent_info = coins[0].parent_coin_info

    # don't need sigs or a proper innersol for eve spend
    spendlist = []
    innersol = binutils.assemble("()")
    for coin in coins:
        spendlist.append((coin, wallet_a.parent_info[coin.parent_coin_info], coin.amount, innersol))
    spend_bundle = wallet_a.cc_generate_eve_spend(spendlist)
    _ = run(remote.push_tx(tx=spend_bundle))

    # update parent info before the information is lost
    #parent_info = dict()  # (coin.parent_coin_info, innerpuzhash, coin.amount)
    #for coin in coins:
    #    parent_info[coin.name()] = (coin.parent_coin_info, ProgramHash(wallet_a.my_coloured_coins[coin][0]), coin.amount)

    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 3
    assert wallet_a.current_balance == 999988500

    # Send 1500 chia to Wallet B - aggregating the 1000 and the 500
    spendslist = []  # spendslist is [] of (coin, parent_info, output_amount, innersol)

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    for coin in coins:
        if coin.amount == 10000:
            coins.remove(coin)
            continue
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': 1500}])
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coins[0]][0], innersol)
    spendslist.append((coins[0], wallet_a.parent_info[coins[0].parent_coin_info], 1500, innersol))
    innersol = Program(binutils.assemble("((q ()) ())"))
    sigs = sigs + wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coins[1]][0], innersol)
    spendslist.append((coins[1], wallet_a.parent_info[coins[1].parent_coin_info], 0, innersol))

    # update parent info before coin disappears
    #parent_info[coins[0].name()] = (coins[0].parent_coin_info, ProgramHash(wallet_a.my_coloured_coins[coins[0]][0]), coins[0].amount)
    #breakpoint()
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list(spendslist, sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert len(wallet_a.my_coloured_coins) == 1
    assert len(wallet_b.my_coloured_coins) == 1
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1500

    # Wallet B breaks down its new coin into 3 coins of value 500
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': wallet_b.get_new_puzzlehash(), 'amount': 400}, {'puzzlehash': wallet_b.get_new_puzzlehash(), 'amount': 500}, {'puzzlehash': wallet_b.get_new_puzzlehash(), 'amount': 600}])
    coin = list(wallet_b.my_coloured_coins.keys()).copy().pop()
    assert coin.parent_coin_info == coins[0].name()
    #breakpoint()
    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[coin][0], innersol)

    spend_bundle = wallet_b.cc_generate_spends_for_coin_list([(coin, wallet_b.parent_info[coin.parent_coin_info], 1500, innersol)], sigs)
    #breakpoint()
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 1
    assert len(wallet_b.my_coloured_coins) == 3


# Test that we can't forge a coloured coin, either through auditing a different colour, or by printing a new coin.
def test_forgery():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates a genesis coin to itself.
    amounts = [10000]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 1
    assert wallet_a.current_balance == 999990000

    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()
    core = wallet_a.my_coloured_coins[coin][1]
    wallet_b.cc_add_core(core)

    # Eve spend coins
    parent_info = coin.parent_coin_info

    # don't need sigs or a proper innersol for eve spend
    spendlist = []
    innersol = binutils.assemble("()")
    spendlist.append((coin, parent_info, coin.amount, innersol))
    spend_bundle = wallet_a.cc_generate_eve_spend(spendlist)
    _ = run(remote.push_tx(tx=spend_bundle))

    # update parent info before the information is lost
    original_eve_parent = parent_info
    parent_info = dict()  # (coin.parent_coin_info, innerpuzhash, coin.amount)
    parent_info = (coin.parent_coin_info, ProgramHash(wallet_a.my_coloured_coins[coin][0]), coin.amount)

    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 1

    # Copy a coins coloured puzzle
    forgedpuzhash = coin.puzzle_hash
    forgedparentcoin = wallet_a.temp_utxos.copy().pop()
    forgedparentinfo = (forgedparentcoin.parent_coin_info, forgedparentcoin.puzzle_hash, forgedparentcoin.amount)
    # Generate new coins with that puzzle
    spend_bundle = wallet_a.generate_signed_transaction(5000, forgedpuzhash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert len(wallet_a.my_coloured_coins) == 2
    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    assert coins[0].puzzle_hash == coins[1].puzzle_hash

    # Try to eve spend the new coin using its own parent info
    spendlist = []
    for coin in coins:
        if coin.amount == 5000:
            spendlist.append((coin, coin.parent_coin_info, coin.amount, innersol))
            continue
    spend_bundle = wallet_a.cc_generate_eve_spend(spendlist)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert coin in wallet_a.my_coloured_coins

    # Try to Eve spend the new coin using the original parent info
    spendlist = []
    for coin in coins:
        if coin.amount == 5000:
            spendlist.append((coin, original_eve_parent, coin.amount, innersol))
            continue
    spend_bundle = wallet_a.cc_generate_eve_spend(spendlist)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert coin in wallet_a.my_coloured_coins

    # Try to regular spend using the information from the real coin
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': 5000}])
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[coin][0], innersol)
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list([(coin, parent_info, 5000, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert coin in wallet_a.my_coloured_coins

    # Try the same spend using the forged parent information
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list([(coin, forgedparentinfo, 5000, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert coin in wallet_a.my_coloured_coins

    # Try to aggregate forged coin with real coin
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': 15000}])
    spendlist = [None] * 2
    for coin in coins:
        if coin.amount == 5000:
            spendlist[1] = (coin, forgedparentinfo, 0, binutils.assemble("(q ())"))
        else:
            spendlist[0] = (coin, parent_info, 15000, innersol)
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list(spendlist, sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert len(wallet_a.my_coloured_coins) == 2
    assert len(wallet_b.my_coloured_coins) == 0


def test_partial_spend_market():
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

    # don't need sigs or a proper innersol for eve spend
    spendslist = []
    innersol = binutils.assemble("()")
    for coin in coins:
        spendslist.append((coin,  coins[0].parent_coin_info, coin.amount, innersol))
    spend_bundle = wallet_a.cc_generate_eve_spend(spendslist)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, wallet_b)

    # Give Wallet B some 1000 of our coloured coin
    spendslist = []
    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    for coin in coins:
        if coin.amount == 1000:
            c = coin
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': 1000}])
    sigs = wallet_a.get_sigs_for_innerpuz_with_innersol(wallet_a.my_coloured_coins[c][0], innersol)
    spendslist.append((c, wallet_a.parent_info[c.parent_coin_info], 1000, innersol))
    spend_bundle = wallet_a.cc_generate_spends_for_coin_list(spendslist, sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, wallet_b)

    assert len(wallet_a.my_coloured_coins) == 2
    assert len(wallet_b.my_coloured_coins) == 1

    # Create market trade (-100 chia, +100 coloured coin)
    spendslist = []
    coins = list(wallet_b.my_coloured_coins.keys()).copy()
    for coin in coins:
        if coin.amount == 1000:
            c = coin
    newinnerpuzhash = wallet_b.get_new_puzzlehash()
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': c.amount + 100}])
    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[c][0], innersol)
    spendslist.append((c, wallet_b.parent_info[c.parent_coin_info], c.amount + 100, innersol))

    c = None
    for coin in wallet_b.temp_utxos:
        if coin.amount >= 100:
            c = coin
    if c is None:
        breakpoint()
    coin = c
    trade_offer = wallet_b.create_trade_offer(coin, coin.amount - 100, spendslist, sigs)
    #breakpoint()
    spend_bundle = wallet_a.parse_trade_offer(trade_offer)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1100
    assert wallet_a.current_balance == 999988600
