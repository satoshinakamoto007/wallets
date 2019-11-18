import asyncio
import clvm
import qrcode
from wallet.rl_wallet import RLWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin
from chiasim.hashable.Body import BodyList
from decorations import print_leaf, divider, prompt
from clvm_tools import binutils
from chiasim.hashable import Program, ProgramHash, BLSSignature
from wallet.puzzle_utilities import pubkey_format, signature_from_string, puzzlehash_from_string, BLSSignature_from_string
from binascii import hexlify
from chiasim.validation import ChainView
from chiasim.ledger.ledger_api import LedgerAPI
from blspy import PublicKey

def print_my_details(wallet):
    print()
    print(divider)
    print(" \u2447 Wallet Details \u2447")
    print()
    print("Name: " + wallet.name)
    print("New pubkey: "+ pubkey_format(wallet.get_next_public_key()))
    print(divider)


def view_funds(wallet):
    print("Current balance: " + str(wallet.current_balance))
    print("Current rate limited balance: " + str(wallet.current_rl_balance))
    print("UTXOs: ")
    print([x.amount for x in wallet.temp_utxos if x.amount > 0])
    if wallet.rl_coin is not None:
        print(f"RL Coin:\nAmount {wallet.rl_coin.amount} \nRate Limit: {wallet.limit}Chia/{wallet.interval}Blocks" )

def receive_rl_coin(wallet):
    print()
    print("Please enter the initialization string:")
    coin_string = input(prompt)
    arr = coin_string.split(":")
    ph = ProgramHash(bytes.fromhex(arr[1]))

    origin = Coin(arr[0], ph, int(arr[2]))
    limit = arr[3]
    interval = arr[4]
    wallet.setOrigin(origin)
    wallet.limit = limit
    wallet.interval = interval
    #puzzlehash = wallet.rl_puzzle_for_pk(wallet.pubkey_orig, limit, interval, origin.name())
    print("Rate limited coin is ready to be received")


async def create_rl_coin(wallet, ledger_api):
    utxo_list = list(wallet.my_utxos)
    print("Select UTXO for origin: ")
    num = 0
    for utxo in utxo_list:
        print(f"{num}) coin_name:{utxo.name()} amount:{utxo.amount}")
        num += 1
    print("Select UTXO for origin")
    selected = int(input(prompt))
    origin = utxo_list[selected]
    print("Rate limit is defined as amount of Chia per time interval.(Blocks)")
    print("Specify the Chia amount limit:")
    rate = int(input(prompt))
    print("Specify the interval length (blocks):")
    interval = int(input(prompt))
    print("Specify the pubkey of receiver")
    pubkey = input(prompt)
    print("Enter amount to give recipient:")
    send_amount = int(input(prompt))
    print(f"Initialization string: {origin.parent_coin_info}:{origin.puzzle_hash}:"
          f"{origin.amount}:{rate}:{interval}")
    print("\nPaste Initialization string to the receiver")
    print("\nPress Enter to continue:")
    input(prompt)
    pubkey = PublicKey.from_bytes(bytes.fromhex(pubkey)).serialize()
    rl_puzzle = wallet.rl_puzzle_for_pk(pubkey, rate, interval, origin.name())
    rl_puzzlehash = ProgramHash(rl_puzzle)
    spend_bundle = wallet.generate_signed_transaction(send_amount, rl_puzzlehash)
    _ = await ledger_api.push_tx(tx=spend_bundle)





async def update_ledger(wallet, ledger_api, most_recent_header):
    if most_recent_header is None:
        r = await ledger_api.get_all_blocks()
    else:
        r = await ledger_api.get_recent_blocks(most_recent_header=most_recent_header)
    update_list = BodyList.from_bytes(r)
    for body in update_list:
        additions = list(additions_for_body(body))
        print(additions)
        removals = removals_for_body(body)
        removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
        spend_bundle_list = wallet.notify(additions, removals)
        #breakpoint()
        if spend_bundle_list is not None:
            for spend_bundle in spend_bundle_list:
                #breakpoint()
                _ = await ledger_api.push_tx(tx=spend_bundle)


async def farm_block(wallet, ledger_api):
    print()
    print(divider)
    print(" \u2447 Commit Block \u2447")
    print()
    print("You have received a block reward.")
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    body = r["body"]
    most_recent_header = r['header']
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bin(await ledger_api.hash_preimage(hash=x)) for x in removals]
    wallet.notify(additions, removals)
    return most_recent_header


async def main():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = RLWallet()
    as_contacts = {}  # 'name': (puzhash)
    as_swap_list = []
    most_recent_header = None
    print_leaf()
    print()
    print("Welcome to your Chia Rate Limited Wallet.")
    print()
    my_pubkey_orig = wallet.get_next_public_key().serialize()
    wallet.pubkey_orig = my_pubkey_orig
    print("Your pubkey is: " + hexlify(my_pubkey_orig).decode('ascii'))

    while selection != "q":
        print()
        print(divider)
        print(" \u2447 Menu \u2447")
        print()
        tip = await ledger_api.get_tip()
        print("Block: ", tip["tip_index"])
        print()
        print("Select a function:")
        print("\u2448 1 Wallet Details")
        print("\u2448 2 View Funds")
        print("\u2448 3 Get Update")
        print("\u2448 4 *GOD MODE* Farm Block / Get Money")
        print("\u2448 5 Receive a new rate limited coin")
        print("\u2448 6 Create a new rate limited coin")
        print("\u2448 7 Spend from rate limited coin")
        print("\u2448 q Quit")
        print(divider)
        print()

        selection = input(prompt)
        if selection == "1":
            print_my_details(wallet)
        if selection == "2":
            view_funds(wallet)
        elif selection == "3":
            await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "4":
            most_recent_header = await farm_block(wallet, ledger_api)
        elif selection == "5":
            receive_rl_coin(wallet)
        elif selection == "6":
            await create_rl_coin(wallet, ledger_api)
        elif selection == "7":
            await create_rl_coin(wallet, ledger_api)


run = asyncio.get_event_loop().run_until_complete
run(main())
