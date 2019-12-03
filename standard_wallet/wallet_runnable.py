import asyncio
import clvm
from utilities.decorations import print_leaf, divider, prompt, start_list, close_list, selectable, informative
from utilities.puzzle_utilities import puzzlehash_from_string
from chiasim.hashable import Coin
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable.Body import BodyList
from clvm_tools import binutils
from chiasim.hashable import Program, ProgramHash
from binascii import hexlify
from authorised_payees import ap_wallet_a_functions
from standard_wallet.wallet import Wallet
try:
    import qrcode
    from PIL import Image
    from pyzbar.pyzbar import decode
except ImportError:
    qrcode = None


def view_funds(wallet):
    print(f"Current balance: {str(wallet.temp_balance)}")
    print(f"UTXOs: {[x.amount for x in wallet.temp_utxos]}")


# def add_contact(wallet):
#     name = input(f"{prompt} What is the new contact's name? ")
#     puzzlegeneratorstring = input(f"{prompt} What is their ChiaLisp puzzlegenerator: ")
#     puzzlegenerator = binutils.assemble(puzzlegeneratorstring)
#     wallet.add_contact(name, puzzlegenerator, 0, None)


# def view_contacts(wallet):
#     print(start_list)
#     for name, details in wallet.contacts:
#         print(name)
#     print(close_list)


def print_my_details(wallet):
    print(f"{informative} Name: {wallet.name}")
    print(f"{informative} Pubkey: {wallet.get_next_public_key()}")
    print(f"{informative} Puzzlehash: {wallet.get_new_puzzlehash()}")


def make_QR(wallet):
    print(divider)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(f"{str(wallet.get_new_puzzlehash())}")
    qr.make(fit=True)
    img = qr.make_image()
    fn = input("Input file name: ")
    if fn.endswith(".jpg"):
        img.save(fn)
    else:
        img.save(f"{fn}.jpg")
    print(f"QR code created in '{fn}.jpg'")


def read_qr(wallet):
    amount = -1
    if wallet.current_balance <= 0:
        print("You need some money first")
        return None
    print("Input filename of QR code: ")
    fn = input(prompt)
    decoded = decode(Image.open(fn))
    puzzlehash = puzzlehash_from_string(str(decoded[0].data))
    while amount > wallet.temp_balance or amount <= 0:
        amount = input("Amount: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)
    return wallet.generate_signed_transaction(amount, puzzlehash)


def set_name(wallet):
    selection = input("Enter a new name: ")
    wallet.set_name(selection)


async def make_payment(wallet, ledger_api):
    amount = -1
    if wallet.current_balance <= 0:
        print("You need some money first")
        return None
    while amount > wallet.temp_balance or amount < 0:
        amount = input(f"{prompt} Enter amount to give recipient: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)

    puzhashstring = input(f"{prompt} Enter puzzlehash: ")
    puzzlehash = puzzlehash_from_string(puzhashstring)
    tx = wallet.generate_signed_transaction(amount, puzzlehash)
    if tx is not None:
        await ledger_api.push_tx(tx=tx)


async def initiate_ap(wallet, ledger_api):
    if wallet.temp_balance <= 0:
        print("You need some money first")
        return None
    # TODO: add a strict format checker to input here (and everywhere tbh)
    # Actual puzzle lockup/spend
    a_pubkey = wallet.get_next_public_key().serialize()
    b_pubkey = input("Enter recipient's pubkey: 0x")
    amount = -1
    while amount > wallet.temp_balance or amount < 0:
        amount = input("Enter amount to give recipient: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)

    APpuzzlehash = ap_wallet_a_functions.ap_get_new_puzzlehash(
        a_pubkey, b_pubkey)
    spend_bundle = wallet.generate_signed_transaction(amount, APpuzzlehash)
    await ledger_api.push_tx(tx=spend_bundle)
    print()
    print(f"{informative} AP Puzzlehash is: {str(APpuzzlehash)}")
    print(f"{informative} Pubkey used is: {hexlify(a_pubkey).decode('ascii')}")
    sig = str(ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
        APpuzzlehash, wallet, a_pubkey).sig)
    print(f"{informative} Approved change signature is: {sig}")
    print()
    print("Give the AP wallet the following initialisation string -")
    print(f"{informative} Initialisation string: {str(APpuzzlehash)}:{hexlify(a_pubkey).decode('ascii')}:{sig}")

    print()
    print("The next step is to approve some contacts for the AP wallet to send to.")
    print("From another standard wallet press '4' to print out their puzzlehash for receiving money.")
    choice = ""
    while choice != "q":
        singlestr = input("Enter approved puzzlehash: ")
        if singlestr == "q":
            return
        puzzlehash = puzzlehash_from_string(singlestr)
        print()
        #print("Puzzle: " + str(puzzlehash))
        sig = wallet.sign(puzzlehash, a_pubkey)
        #print("Signature: " + str(sig.sig))
        name = input("Add a name for this puzzlehash: ")
        print("Give the following contact string to the AP wallet.")
        print(f"{informative} Contact string for AP Wallet: {name}:{str(puzzlehash)}:{str(sig.sig)}")
        choice = input("Press 'c' to continue, or 'q' to quit to menu: ")


async def new_block(wallet, ledger_api):
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    body = r["body"]
    # breakpoint()
    most_recent_header = r['header']
    # breakpoint()
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    wallet.notify(additions, removals)
    return most_recent_header


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
        wallet.notify(additions, removals)


async def main_loop():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = Wallet()
    print(divider)
    print_leaf()
    most_recent_header = None
    while selection != "q":
        print(divider)
        view_funds(wallet)
        print(divider)
        print(start_list)
        print("Select a function:")
        print(f"{selectable} 1: Make Payment")
        print(f"{selectable} 2: Get Update")
        print(f"{selectable} 3: *GOD MODE* Commit Block / Get Money")
        print(f"{selectable} 4: Print my details for somebody else")
        print(f"{selectable} 5: Set my wallet name")
        print(f"{selectable} 6: Initiate Authorised Payee")
        if qrcode:
            print(f"{selectable} 7: Make QR code")
            print(f"{selectable} 8: Payment to QR code")
        print(f"{selectable} q: Quit")
        print(close_list)
        selection = input(prompt)
        if selection == "1":
            r = await make_payment(wallet, ledger_api)
        elif selection == "2":
            await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "3":
            most_recent_header = await new_block(wallet, ledger_api)
        elif selection == "4":
            print_my_details(wallet)
        elif selection == "5":
            set_name(wallet)
        elif selection == "6":
            await initiate_ap(wallet, ledger_api)
        if qrcode:
            if selection == "7":
                make_QR(wallet)
            elif selection == "8":
                r = read_qr(wallet)
                if r is not None:
                    await ledger_api.push_tx(tx=r)


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
