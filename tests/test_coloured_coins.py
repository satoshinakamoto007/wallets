import asyncio
import pathlib
import tempfile
import clvm
from aiter import map_aiter
from coloured_coins.cc_wallet import CCWallet
from standard_wallet.wallet import Wallet
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin, Program, ProgramHash, SpendBundle, CoinSolution
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

    # Wallet A generates some eve coins to itself.
    amount = 10000
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins([amount])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert len(wallet_a.my_coloured_coins) == 1

    # Wallet A does Eve spend to itself
    innersol = binutils.assemble("()")

    coin = list(wallet_a.my_coloured_coins.keys()).copy().pop()
    core = wallet_a.my_coloured_coins[coin][1]
    wallet_b.cc_add_core(core)
    assert ProgramHash(clvm.to_sexp_f(wallet_a.cc_make_puzzle(ProgramHash(wallet_a.my_coloured_coins[coin][0]), core))) == coin.puzzle_hash
    assert len(wallet_b.my_coloured_coins) == 0
    assert len(wallet_a.my_coloured_coins) == 1
    assert wallet_a.current_balance == 1000000000 - amount

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
    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[coin][0], innersol)

    spend_bundle = wallet_b.cc_generate_spends_for_coin_list([(coin, wallet_b.parent_info[coin.parent_coin_info], 1500, innersol)], sigs)
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


def test_multiple_genesis_coins():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    # A gives some unique coloured Chia coins to B who is then able to spend it while retaining the colouration
    wallet_a = CCWallet()
    wallets = [wallet_a]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates splits its coin.
    my_utxos_copy = wallet_a.temp_utxos.copy()
    coin = my_utxos_copy.pop()
    while coin.amount < 1:
        coin = my_utxos_copy.pop()

    pubkey, secretkey = wallet_a.get_keys(coin.puzzle_hash)
    puzzle = wallet_a.puzzle_for_pk(pubkey)
    solution = wallet_a.make_solution(primaries=[{'puzzlehash': wallet_a.get_new_puzzlehash(), 'amount': 9000}, {'puzzlehash': wallet_a.get_new_puzzlehash(), 'amount': 400}, {'puzzlehash': wallet_a.get_new_puzzlehash(), 'amount': 1200}])
    spend_bundle = wallet_a.sign_transaction([(puzzle, CoinSolution(coin, solution))])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.temp_utxos) == 4
    assert wallet_a.current_balance == 10600


    # Generate coloured coin
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins([10000])
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 1

    assert len(wallet_a.my_coloured_coins) == 1
    assert coin not in wallet_a.my_coloured_coins
    assert wallet_a.current_balance == 600

    return


def test_trade():
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
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1000
    assert sum(x.amount for x in list(wallet_a.my_coloured_coins.keys())) == 10500

    # Create market trade (-100 chia, +100 coloured coin)
    trade_offer = wallet_b.create_trade_offer([(-100, None), (100, core)])
    trade_offer_hex = bytes(trade_offer).hex()

    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    spend_bundle = wallet_a.parse_trade_offer(received_offer)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1100
    assert wallet_a.current_balance == 999988600


    # Create market trade (+100 chia, -100 coloured coin)
    trade_offer = wallet_b.create_trade_offer([(100, None), (-100, core)])
    trade_offer_hex = bytes(trade_offer).hex()

    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    spend_bundle = wallet_a.parse_trade_offer(received_offer)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 1000
    assert sum(x.amount for x in list(wallet_a.my_coloured_coins.keys())) == 10500


def test_trade_with_zero_val():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates a genesis coins to itself.
    amounts = [1000]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, wallet_b)
    assert len(wallet_a.my_coloured_coins) == 1
    assert wallet_a.current_balance == 999999000

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    core = wallet_a.my_coloured_coins[coins[0]][1]
    wallet_b.cc_add_core(core)

    # Wallet B makes a zero val copy of A's colour

    spend_bundle = wallet_b.cc_create_zero_val_for_core(core)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 1
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 0

    # Create market trade (-100 chia, +100 coloured coin)
    trade_offer = wallet_b.create_trade_offer([(-100, None), (100, core)])
    trade_offer_hex = bytes(trade_offer).hex()

    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    spend_bundle = wallet_a.parse_trade_offer(received_offer)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    assert list(wallet_b.my_coloured_coins.keys()).copy().pop().amount == 100
    assert wallet_a.current_balance == 999999100


def test_zero_val_no_trade():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)
    # Wallet A generates a genesis coins to itself.
    amounts = [1000]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, wallet_b)
    assert len(wallet_a.my_coloured_coins) == 1
    assert wallet_a.current_balance == 999999000

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    core = wallet_a.my_coloured_coins[coins[0]][1]
    wallet_b.cc_add_core(core)

    # Wallet B makes a zero val copy of A's colour

    spend_bundle = wallet_b.cc_create_zero_val_for_core(core)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 1
    coin = list(wallet_b.my_coloured_coins.keys()).copy().pop()
    assert coin.amount == 0
    innersol = wallet_b.make_solution(primaries=[{'puzzlehash': wallet_a.get_new_puzzlehash(), 'amount': 0}])

    sigs = wallet_b.get_sigs_for_innerpuz_with_innersol(wallet_b.my_coloured_coins[coin][0], innersol)

    spend_bundle = wallet_b.cc_generate_spends_for_coin_list([(coin, wallet_b.parent_info[coin.parent_coin_info], 0, innersol)], sigs)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_a.my_coloured_coins) == 2


def test_trade_multiple_colours():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates a set of genesis coins to itself.
    amounts = [100, 200, 300, 400]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, wallet_b)
    assert len(wallet_a.my_coloured_coins) == 4
    assert wallet_a.current_balance == 999999000

    coins = list(wallet_a.my_coloured_coins.keys()).copy()
    core_a = wallet_a.my_coloured_coins[coins[0]][1]
    wallet_b.cc_add_core(core_a)

    # Wallet B generates a new set of genesis coins to itself.
    amounts = [400, 500, 600]
    spend_bundle = wallet_b.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert len(wallet_b.my_coloured_coins) == 3
    assert wallet_b.current_balance == 999998500

    coins = list(wallet_b.my_coloured_coins.keys()).copy()
    core_b = wallet_b.my_coloured_coins[coins[0]][1]
    wallet_a.cc_add_core(core_b)

    # Wallet B makes a zero val copy of A's colour

    spend_bundle = wallet_b.cc_create_zero_val_for_core(core_a)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    # Wallet A makes a zero val copy of B's colour

    spend_bundle = wallet_a.cc_create_zero_val_for_core(core_b)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    # Create market trade (-150 colour b, +100 colour a)
    trade_offer = wallet_b.create_trade_offer([(-150, core_b), (900, core_a)])
    trade_offer_hex = bytes(trade_offer).hex()

    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    spend_bundle = wallet_a.parse_trade_offer(received_offer)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())
    #breakpoint()
    assert wallet_a.current_balance == 999999000
    assert wallet_b.current_balance == 999998500
    assert wallet_a.cc_select_coins_for_colour(wallet_a.get_genesis_from_core(core_b), 100) is not None
    assert wallet_b.cc_select_coins_for_colour(wallet_b.get_genesis_from_core(core_a), 100) is not None


def test_trade_with_auto_generate():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete

    wallet_a = CCWallet()
    wallet_b = CCWallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    # Wallet A generates a set of genesis coins to itself.
    amounts = [100, 200, 300, 400]
    spend_bundle = wallet_a.cc_generate_spend_for_genesis_coins(amounts)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, wallet_b)
    assert len(wallet_a.my_coloured_coins) == 4
    assert wallet_a.current_balance == 999999000

    core_a = wallet_a.my_cores.copy().pop()

    trade_offer = wallet_a.create_trade_offer([(3000, None), (-500, core_a)])
    trade_offer_hex = bytes(trade_offer).hex()

    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    spend_bundle = wallet_b.parse_trade_offer(received_offer)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert sum(x.amount for x in wallet_b.my_coloured_coins) == 500
    assert wallet_a.current_balance == 1000002000
