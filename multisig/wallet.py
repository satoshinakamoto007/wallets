import asyncio
import json
import readline  # noqa
from pathlib import Path

# We import readline to allow extremely long cut & paste text strings

from chiasim.hashable import (
    BLSSignature,
    Coin,
    CoinSolution,
    SpendBundle,
)
from chiasim.validation import validate_spend_bundle_signature
from chiasim.validation.Conditions import make_create_coin_condition

from .full_node import generate_coins, ledger_sim_proxy, sync
from .pst import PartiallySignedTransaction
from .storage import Storage
from .BLSHDKeys import BLSPublicHDKey, fingerprint_for_pk
from .MultisigHDWallet import MultisigHDWallet

from chiasim.puzzles.p2_m_of_n_delegate_direct import solution_for_delegated_puzzle
from chiasim.puzzles.p2_conditions import puzzle_for_conditions, solution_for_conditions
from chiasim.validation.consensus import (
    conditions_dict_for_solution,
    hash_key_pairs_for_conditions_dict,
)


GAP_LIMIT = 100  # TODO: fix this


def pubkey_for_str(s):
    k = bytes.fromhex(s)
    if len(k) == 93:
        return k
    return None


def create_wallet(path, input=input):
    print("Creating M of N wallet")
    pubkeys = []
    while True:
        pubkey_str = input("Enter a public hd key> ")
        if len(pubkey_str) == 0:
            break
        pubkey = pubkey_for_str(pubkey_str)
        if pubkey is None:
            print("invalid format")
            continue
        pubkeys.append(pubkey)
    N = len(pubkeys)
    print(f"entered {N} keys, so N = {N}")
    while True:
        M_str = input(f"what is M [1-{N}]> ")
        try:
            M = int(M_str)
        except ValueError:
            M = 0
        if 1 <= M <= N:
            break
        print("try again")
    pubkeys_hex = [_.hex() for _ in pubkeys]
    d = dict(public_hd_keys=pubkeys_hex, M=M)
    with open(path, "w") as f:
        json.dump(d, f)
    return d


def load_wallet(path) -> MultisigHDWallet:
    d = json.load(open(path))
    pub_hd_keys_bytes = [bytes.fromhex(_) for _ in d["public_hd_keys"]]
    pub_hd_keys = [BLSPublicHDKey.from_bytes(_) for _ in pub_hd_keys_bytes]
    wallet = MultisigHDWallet(d["M"], pub_hd_keys)
    return wallet


async def do_generate_address(wallet, storage, full_node, input):
    index_str = input("Choose index (integer >= 0)> ")
    try:
        index = int(index_str)
    except ValueError:
        pass
    address = wallet.address_for_index(index)
    print(f"address #{index} is {address}")
    r = input(f"Generate coins with this address? (y/n)> ")
    if r.lower().startswith("y"):
        puzzle_hash = wallet.puzzle_hash_for_index(index)
        await generate_coins(wallet, full_node, puzzle_hash, puzzle_hash)
        await do_sync(wallet, storage, full_node)
    return address


async def do_spend_coin(wallet, storage, full_node, input):
    coins = []
    while True:
        coin_str = input("Enter hex id of coin to spend> ")
        if len(coin_str) == 0:
            break
        coin_name = bytes.fromhex(coin_str)
        preimage = await storage.hash_preimage(hash=coin_name)
        if preimage is None:
            print(f"can't find coin id {coin_name.hex()}")
            continue
        coin = Coin.from_bytes(preimage)
        coin_puzzle_hash_hex = coin.puzzle_hash.hex()
        print(f"coin puzzle hash is {coin_puzzle_hash_hex}")
        coins.append(coin)
    if len(coins) == 0:
        return
    dest_address = "14c56fdefb47e2208de54b6c609a907c522348c96e8cfb41c7a8c75f44835dd9"
    print(f"sending 1 coin to {dest_address}, rest fees")
    pst = spend_coin(wallet, coins, dest_address)
    pst_encoded = bytes(pst)
    print(pst_encoded.hex())
    sigs = []
    while True:
        sig_str = input("Enter a signature> ")
        try:
            sig = BLSSignature.from_bytes(bytes.fromhex(sig_str))
        except Exception as ex:
            print("failed: %s" % ex)
            continue
        sigs.append(sig)
        sigs = list(set(sigs))
        spend_bundle, summary_list = finalize_pst(wallet, pst, sigs)
        if spend_bundle:
            break
        for summary in summary_list:
            print(
                "coin %s has %d of %d sigs"
                % (summary[0].name(), len(summary[2]), summary[3])
            )
    print("spend bundle = %s" % bytes(spend_bundle).hex())
    r = input(f"Send to ledgersim? (y/n)> ")
    if r.lower().startswith("y"):
        r = await full_node.push_tx(tx=spend_bundle)
    return spend_bundle


def solution_for_coin(wallet, index, coin, conditions):
    delegated_puzzle = puzzle_for_conditions(conditions)
    delegated_solution = solution_for_conditions(conditions)

    pub_keys = wallet.pub_keys_for_index(index)
    n = len(pub_keys)
    maximal_solution = solution_for_delegated_puzzle(
        n, pub_keys, [1] * n, delegated_puzzle, delegated_solution
    )
    return CoinSolution(coin, maximal_solution), pub_keys


def spend_coin(wallet, coins, dest_address):
    conditions = [make_create_coin_condition(bytes.fromhex(dest_address), 1)]
    m = wallet.m()

    coin_solutions = []
    hd_hints = {}
    for coin in coins:
        index = wallet.index_for_puzzle_hash(coin.puzzle_hash, GAP_LIMIT)
        coin_solution, pub_keys = solution_for_coin(wallet, index, coin, conditions)
        coin_solutions.append(coin_solution)
        new_hints = {
            fingerprint_for_pk(_.public_child(index)): dict(
                hd_fingerprint=_.fingerprint(), index=index
            )
            for _ in wallet.pub_hd_keys()
        }
        hd_hints.update(new_hints)
    pst = PartiallySignedTransaction(
        coin_solutions=coin_solutions,
        hd_hints=hd_hints,
        multisig=dict(m=m, pub_keys=pub_keys),
        conditions=conditions,
    )
    return pst


def sigs_to_aggsig_sig_dict(wallet, pst, sigs):
    # this n^2 algorithm matches signatures to aggsig
    all_sigs_dict = {}
    all_aggsigs = set()
    for coin_solution in pst.get("coin_solutions"):
        solution = coin_solution.solution
        conditions_dict = conditions_dict_for_solution(solution)
        hkp_list = hash_key_pairs_for_conditions_dict(conditions_dict)
        all_aggsigs.update(hkp_list)
    for sig in sigs:
        for aggsig in all_aggsigs:
            if sig.validate([aggsig]):
                all_sigs_dict[aggsig] = sig
                all_aggsigs.remove(aggsig)
                break
    return all_sigs_dict


def finalize_pst(wallet, pst, sigs):
    # figure out which keys we have signatures for

    m = wallet.m()
    coin_solutions = []
    sig_dict = sigs_to_aggsig_sig_dict(wallet, pst, sigs)

    all_sigs_to_use = []

    summary_list = []

    for coin_solution in pst.get("coin_solutions"):
        coin, solution = coin_solution.coin, coin_solution.solution
        # run maximal_solution and get conditions
        conditions_dict = conditions_dict_for_solution(solution)
        # look for AGG_SIG conditions
        hkp_list = hash_key_pairs_for_conditions_dict(conditions_dict)
        # see if we have enough info to build signatures
        found_list = []
        sigs_to_use = []
        for aggsig_pair in hkp_list:
            add_me = 0
            if len(sigs_to_use) < m:
                if aggsig_pair in sig_dict:
                    sigs_to_use.append(sig_dict[aggsig_pair])
                    add_me = 1
            found_list.append(add_me)

        all_sigs_to_use.extend(sigs_to_use)

        conditions = pst.get("conditions")
        delegated_puzzle = puzzle_for_conditions(conditions)
        delegated_solution = solution_for_conditions(conditions)

        index = wallet.index_for_puzzle_hash(coin.puzzle_hash, GAP_LIMIT)
        pub_keys = wallet.pub_keys_for_index(index)
        actual_solution = solution_for_delegated_puzzle(
            m, pub_keys, found_list, delegated_puzzle, delegated_solution
        )

        coin_solution = CoinSolution(coin, actual_solution)
        coin_solutions.append(coin_solution)
        summary = (coin, hkp_list, sigs_to_use, m)
        summary_list.append(summary)

    if len(all_sigs_to_use) > 0:
        aggregated_sig = all_sigs_to_use[0].aggregate(all_sigs_to_use)
        spend_bundle = SpendBundle(coin_solutions, aggregated_sig)
        try:
            if validate_spend_bundle_signature(spend_bundle):
                return spend_bundle, summary_list
        except Exception:
            pass

    return None, summary_list


async def all_coins_and_unspents(storage):
    coins = []
    unspents = []
    coin_name_unspent_pairs = [_ async for _ in storage.all_unspents()]
    for coin_name, unspent in coin_name_unspent_pairs:
        preimage = await storage.hash_preimage(hash=coin_name)
        coin = Coin.from_bytes(preimage)
        unspents.append(unspent)
        coins.append(coin)
    return coins, unspents


async def do_sync(wallet, storage, full_node):
    storage.add_interested_puzzle_hashes(
        wallet.puzzle_hash_for_index(_) for _ in range(GAP_LIMIT)
    )
    r = await sync(storage, full_node)
    noun = "block" if r == 1 else "blocks"
    print(f"{r} new {noun} loaded")

    coins, unspents = await all_coins_and_unspents(storage)
    print(f"Coin count: {len(coins)}")
    for coin, unspent in zip(coins, unspents):
        if unspent.spent_block_index == 0:
            print(
                f"{coin.name().hex()}  {coin.amount:12}  {unspent.confirmed_block_index:4}"
            )


async def menu(wallet, storage, full_node, input):
    print("Choose:")
    print("1. Generate an address")
    print("2. Spend a coin")
    print("3. Sync")
    print("q. Quit")
    choice = input("> ")
    if choice == "1":
        await do_generate_address(wallet, storage, full_node, input)
    if choice == "2":
        await do_spend_coin(wallet, storage, full_node, input)
    if choice == "3":
        await do_sync(wallet, storage, full_node)
    return choice != "q"


async def main_loop(path, storage=None, input=input):
    full_node = await ledger_sim_proxy()
    if storage is None:
        storage = Storage("junk path")

    if not path.exists():
        create_wallet(path, input)
    wallet = load_wallet(path)
    while True:
        should_continue = await menu(wallet, storage, full_node, input)
        if not should_continue:
            break


def main(path=Path("multisig-wallet.json"), input=input):
    asyncio.get_event_loop().run_until_complete(main_loop(path, input=input))


if __name__ == "__main__":
    main()
