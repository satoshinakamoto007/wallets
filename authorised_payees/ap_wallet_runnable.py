import asyncio
from authorised_payees.ap_wallet import APWallet
from authorised_payees.ap_wallet_a_functions import ap_get_aggregation_puzzlehash
from utilities.decorations import print_leaf, divider, prompt, start_list, close_list, selectable, informative
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable.Body import Body
from chiasim.hashable import Coin, Header, HeaderHash
from utilities.puzzle_utilities import pubkey_format, puzzlehash_from_string, BLSSignature_from_string
from binascii import hexlify


def view_funds(wallet):
    if wallet.temp_coin is not None:
        print(f"Current balance: {str(wallet.temp_coin.amount)}")
        return
    else:
        print("Current balance: 0")
        return


def add_contact(wallet, approved_puzhash_sig_pairs):
    choice = "c"
    print(divider)
    while choice == "c":
        singlestring = input("Enter contact string from authoriser: ")
        if singlestring == "q":
            return
        try:
            arr = singlestring.split(":")
            name = arr[0]
            puzzle = arr[1]
            puzhash = puzzlehash_from_string(puzzle)
            sig = arr[2]
            signature = BLSSignature_from_string(sig)
            while name in approved_puzhash_sig_pairs:
                print(f"{name} is already a contact. Would you like to add a new contact or overwrite {name}?")
                print(f"{selectable} 1: Overwrite")
                print(f"{selectable} 2: Add new contact")
                print(f"{selectable} q: Return to menu")
                pick = input(prompt)
                if pick == "q":
                    return
                elif pick == "1":
                    continue
                elif pick == "2":
                    name = input("Enter new name for contact: ")
            approved_puzhash_sig_pairs[name] = (puzhash, signature)
            choice = input("Press 'c' to add another, or 'q' to return to menu: ")
        except Exception as err:
            print(err)
            return


def view_contacts(approved_puzhash_sig_pairs):
    for name in approved_puzhash_sig_pairs:
        print(f" - {name}")


def print_my_details(wallet):
    print(divider)
    print(f"{informative} Name: {wallet.name}")
    print(f"{informative} New pubkey: {hexlify(wallet.get_next_public_key().serialize()).decode('ascii')}")
    print(f"{informative} Puzzlehash: {ap_get_aggregation_puzzlehash(wallet.AP_puzzlehash)}")


def set_name(wallet):
    selection = input("Enter your new name: ")
    wallet.set_name(selection)


def make_payment(wallet, approved_puzhash_sig_pairs):
    amount = -1
    if wallet.current_balance <= 0:
        print("You need some money first")
        return
    print(start_list)
    print("Select a contact from approved list: ")
    for name in approved_puzhash_sig_pairs:
        print(f" - {name}")
    print(close_list)
    choice = input("Name of payee: ")
    if choice not in approved_puzhash_sig_pairs:
        print("invalid contact")
        return

    while amount > wallet.temp_coin.amount or amount < 0:
        amount = input("Enter amount to give recipient: ")
        if not amount.isdigit():
            amount = -1
        if amount == "q":
            return
        amount = int(amount)

    puzzlehash = approved_puzhash_sig_pairs[choice][0]
    return wallet.ap_generate_signed_transaction([(puzzlehash, amount)], [approved_puzhash_sig_pairs[choice][1]])


async def process_blocks(wallet, ledger_api, last_known_header, current_header_hash):
    r = await ledger_api.hash_preimage(hash=current_header_hash)
    header = Header.from_bytes(r)
    body = Body.from_bytes(await ledger_api.hash_preimage(hash=header.body_hash))
    if header.previous_hash != last_known_header:
        await process_blocks(wallet, ledger_api, last_known_header, header.previous_hash)
    print(f'processing block {HeaderHash(header)}')
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    spend_bundle_list = wallet.notify(additions, removals)
    if spend_bundle_list is not None:
        for spend_bundle in spend_bundle_list:
            _ = await ledger_api.push_tx(tx=spend_bundle)


async def update_ledger(wallet, ledger_api, most_recent_header):
    r = await ledger_api.get_tip()
    if r['tip_hash'] != most_recent_header:
        await process_blocks(wallet,
                             ledger_api,
                             r['genesis_hash'] if most_recent_header is None else most_recent_header,
                             r['tip_hash'])
    return r['tip_hash']


def ap_settings(wallet, approved_puzhash_sig_pairs):
    print(divider)
    print(f"{selectable} 1: Add Authorised Payee")
    print(f"{selectable} 2: Change initialisation settings")
    print("WARNING: This is only for if you messed it up the first time.")
    print("Press 'c' to continue or any other key to return")
    choice = input(prompt)
    if choice != "c":
        return
    print(f"Your pubkey is: {pubkey_format(wallet.get_next_public_key())}")
    print("Please fill in some initialisation information (this can be changed later)")
    print("Please enter initialisation string: ")
    init_string = input(prompt)
    arr = init_string.split(":")
    AP_puzzlehash = arr[0]
    a_pubkey = arr[1]
    wallet.set_sender_values(AP_puzzlehash, a_pubkey)
    sig = BLSSignature_from_string(arr[2])
    wallet.set_approved_change_signature(sig)


async def main_loop():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = APWallet()
    approved_puzhash_sig_pairs = {}  # 'name': (puzhash, signature)
    most_recent_header = None
    print(divider)
    print_leaf()
    print(divider)
    print("Welcome to AP Wallet")
    print(f"Your pubkey is: {hexlify(wallet.get_next_public_key().serialize()).decode('ascii')}")
    print("To start an AP wallet, it must be initialised from a standard wallet.")
    print("From a standard wallet and press `6` and enter the pubkey above.")
    complete = False
    while complete is False:
        print("Please enter initialisation string: ")
        init_string = input()
        try:
            arr = init_string.split(":")
            AP_puzzlehash = arr[0]
            a_pubkey = arr[1]
            wallet.set_sender_values(AP_puzzlehash, a_pubkey)
            sig = BLSSignature_from_string(arr[2])
            wallet.set_approved_change_signature(sig)
            complete = True
        except Exception:
            print("Invalid initialisation string. Please try again")
    add_contact(wallet, approved_puzhash_sig_pairs)
    while selection != "q":
        print(divider)
        view_funds(wallet)
        print(divider)
        print(start_list)
        print("Select a function:")
        print(f"{selectable} 1: Add Payee")
        print(f"{selectable} 2: Make Payment")
        print(f"{selectable} 3: View Payees")
        print(f"{selectable} 4: Get Update")
        print(f"{selectable} 5: Print my details for somebody else")
        print(f"{selectable} 6: Set my wallet detail")
        print(f"{selectable} 7: AP Settings")
        print(f"{selectable} q: Quit")
        print(close_list)
        selection = input(prompt)
        if selection == "1":
            add_contact(wallet, approved_puzhash_sig_pairs)
        elif selection == "2":
            r = make_payment(wallet, approved_puzhash_sig_pairs)
            if r is not None:
                await ledger_api.push_tx(tx=r)
        elif selection == "3":
            view_contacts(approved_puzhash_sig_pairs)
        elif selection == "4":
            await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "5":
            print_my_details(wallet)
        elif selection == "6":
            set_name(wallet)
        elif selection == "7":
            ap_settings(wallet, approved_puzhash_sig_pairs)


def main():
    run = asyncio.get_event_loop().run_until_complete
    run(main_loop())


if __name__ == "__main__":
    main()

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
