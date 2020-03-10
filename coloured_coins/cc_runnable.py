import asyncio
from utilities.decorations import print_leaf, divider, prompt, start_list, close_list, selectable
from utilities.puzzle_utilities import puzzlehash_from_string
from chiasim.hashable import Coin, Header, HeaderHash, SpendBundle
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable.Body import Body, Program
from clvm_tools import binutils
from standard_wallet.wallet_runnable import make_payment, set_name, print_my_details
from coloured_coins.cc_wallet import CCWallet


def view_funds(wallet):
    print(f"Current balance: {str(wallet.temp_balance)}")
    print(f"UTXOs: {[x.amount for x in wallet.temp_utxos]}")
    print(f"Coloured Coin info:")
    for x in list(wallet.my_coloured_coins.keys()):
        print("  ------------------------------------")
        print(f"  Name:   {x.name()}")
        print(f"  Colour: {wallet.get_genesis_from_core(wallet.my_coloured_coins[x][1])}")
        print(f"  Amount: {x.amount}")
    print("------------------------------------")
    print(f"CC Total: {sum(x.amount for x in list(wallet.my_coloured_coins.keys()))}")


async def farm_block(wallet, ledger_api, last_known_header):
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    header = r['header']
    header_hash = HeaderHash(header)
    tip = await ledger_api.get_tip()
    await process_blocks(wallet,
                         ledger_api,
                         tip['genesis_hash'] if last_known_header is None else last_known_header,
                         header_hash)
    return header_hash


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
    wallet.notify(additions, removals, body)


async def update_ledger(wallet, ledger_api, most_recent_header):
    r = await ledger_api.get_tip()
    if r['tip_hash'] != most_recent_header:
        await process_blocks(wallet,
                             ledger_api,
                             r['genesis_hash'] if most_recent_header is None else most_recent_header,
                             r['tip_hash'])
    return r['tip_hash']


async def choose_payment_type(wallet, ledger_api):
    print()
    print(f"    {selectable} 1: Uncoloured")
    print(f"    {selectable} 2: Coloured")
    selection = input(prompt)
    if selection == "1":
        make_payment(wallet, ledger_api)
        return
    elif selection == "2":
        await make_cc_payment(wallet, ledger_api)
        return


async def make_cc_payment(wallet, ledger_api):
    print("What colour coins would you like to spend?")
    colour = input(prompt)
    if colour == "q":
        return
    print("How much value of that colour would you like to send?")
    amount = input(prompt)
    if amount == "q":
        return
    else:
        amount = int(amount)
    coins = wallet.cc_select_coins_for_colour(colour, amount)
    if coins is None:
        print("You do not have enough of that colour.")
        return
    print("Please enter the recipient's puzzlehash:")
    newinnerpuzhash = puzzlehash_from_string(input(prompt))
    actual_total = sum(x.amount for x in coins)
    change = actual_total - amount
    spendslist = []
    innersol = wallet.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': amount},{'puzzlehash': wallet.get_new_puzzlehash(), 'amount': change}])
    sigs = wallet.get_sigs_for_innerpuz_with_innersol(wallet.my_coloured_coins[coins[0]][0], innersol)
    spendslist.append((coins[0], wallet.parent_info[coins[0].parent_coin_info], actual_total, innersol))
    innersol = Program(binutils.assemble("((q ()) ())"))
    for coin in coins[1:]:
        sigs = sigs + wallet.get_sigs_for_innerpuz_with_innersol(wallet.my_coloured_coins[coin][0], innersol)
        spendslist.append((coin, wallet.parent_info[coin.parent_coin_info], 0, innersol))
    spend_bundle = wallet.cc_generate_spends_for_coin_list(spendslist, sigs)
    await ledger_api.push_tx(tx=spend_bundle)
    return


async def create_zero_val(wallet, ledger_api):
    print("Enter a colour to print: ")
    colour = input(prompt)
    core = wallet.cc_make_core(colour)
    wallet.my_cores.add(core)
    spend_bundle = wallet.cc_create_zero_val_for_core(core)
    await ledger_api.push_tx(tx=spend_bundle)
    return


def create_offer(wallet):
    trade_list = []
    print("Do you want to use chia in this transaction or just use coloured coins?")
    print("1: Use chia")
    print("2: Just coloured coins")
    choice = input(prompt)
    if choice == "1":
        print("Enter an amount you want to spend or gain - i.e '-100' '250':")
        amount = input(prompt)
        amount = int(amount)
        trade_list.append((amount, None))
    elif choice == "2":
        print("Enter a colour you want to spend or gain:")
        colour = input(prompt)
        print("Enter the relative amount - i.e '-100' '250':")
        amount = int(input(prompt))
        trade_list.append((amount,  wallet.cc_make_core(colour)))
    else:
        return

    complete = False
    while complete is False:
        print("Enter a colour you want to spend or gain:")
        colour = input(prompt)
        print("Enter the relative amount - i.e '-100' '250':")
        amount = int(input(prompt))
        trade_list.append((amount, wallet.cc_make_core(colour)))
        print("Do you want to add another element (y/n): ")
        choice = input(prompt)
        if choice == "n":
            complete = True

    trade_offer = wallet.create_trade_offer(trade_list)
    trade_offer_hex = bytes(trade_offer).hex()
    print("Enter the filename to store your offer in: ")
    filename = input(prompt)
    f = open(filename, "w")
    f.write(trade_offer_hex)
    f.close()
    print(f"Your trade offer is written to {filename}.")
    return


async def respond_to_offer(wallet, ledger_api):
    print("Enter the filename offer is stored in: ")
    filename = input(prompt)
    f = open(filename, "r")
    trade_offer_hex = f.read()
    f.close()
    received_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
    cc_discrepancies = wallet.get_relative_amounts_for_trade_offer(received_offer)
    print("This offer is: ")
    for colour in cc_discrepancies:
        if colour is None:
            print(f"chia: {cc_discrepancies[None]}")
        else:
            print(f"{colour}: {cc_discrepancies[colour]}")
    print("Do you accept? (y/n)")
    choice = input(prompt)
    if choice == "y":
        spend_bundle = wallet.parse_trade_offer(received_offer)
        await ledger_api.push_tx(tx=spend_bundle)
    return


async def create_new_cc_batch(wallet, ledger_api):
    print(divider)
    if (wallet.temp_balance <= 0):
        print("You need to have some chia first")
        return

    print(f"Your current balance: {wallet.temp_balance}")
    print()
    print("How many new coins would you like to create?")
    number = input(prompt)
    if number == "q":
        return
    else:
        number = int(number)

    amounts = [None] * number
    for i in range(len(amounts)):
        print(f"How much value for coin #{i}?")
        number = input(prompt)
        if number == "q":
            return
        else:
            amounts[i] = int(number)
    if sum(amounts) > wallet.temp_balance:
        print("You do not have enough money for those amounts.")
        return
    spend_bundle = wallet.cc_generate_spend_for_genesis_coins(amounts)
    await ledger_api.push_tx(tx=spend_bundle)
    return


async def main_loop():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = CCWallet()
    print(divider)
    print_leaf()
    r = await ledger_api.get_tip()
    most_recent_header = r['genesis_hash']
    while selection != "q":
        print(divider)
        view_funds(wallet)
        print(divider)
        print(start_list)
        print("Select a function:")
        print(f"{selectable} 1: Make Payment")
        print(f"{selectable} 2: Get Update")
        print(f"{selectable} 3: Farm Block")
        print(f"{selectable} 4: Print my details for somebody else")
        print(f"{selectable} 5: Set my wallet name")
        print(f"{selectable} 6: Coloured Coins Options")
        print(f"{selectable} 7: Trade Offer Options")
        print(f"{selectable} q: Quit")
        print(close_list)
        selection = input(prompt)
        if selection == "1":
            r = await choose_payment_type(wallet, ledger_api)
        elif selection == "2":
            most_recent_header = await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "3":
            most_recent_header = await farm_block(wallet, ledger_api, most_recent_header)
        elif selection == "4":
            print_my_details(wallet)
        elif selection == "5":
            set_name(wallet)
        elif selection == "6":
            print()
            print(f" {selectable} 1: Add Colour")
            print(f" {selectable} 2: Generate New Colour")
            print(f" {selectable} 3: Print a 0-value Coloured Coin")
            selection = input(prompt)
            if selection == "1":
                print("Enter colour: ")
                colour = input(prompt)
                if colour[0:2] == "0x":
                    colour = colour[2:]
                core = wallet.cc_make_core(colour)
                wallet.cc_add_core(core)
            elif selection == "2":
                await create_new_cc_batch(wallet, ledger_api)
            elif selection == "3":
                await create_zero_val(wallet, ledger_api)
        elif selection == "7":
            print()
            print(f" {selectable} 1: Create Offer")
            print(f" {selectable} 2: Respond to Offer")
            selection = input(prompt)
            if selection == "1":
                create_offer(wallet)
            elif selection == "2":
                await respond_to_offer(wallet, ledger_api)


def main():
    run = asyncio.get_event_loop().run_until_complete
    run(main_loop())


if __name__ == "__main__":
    main()


"""
Copyright 2020 Chia Network Inc
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
