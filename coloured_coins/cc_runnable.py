import asyncio
from utilities.decorations import print_leaf, divider, prompt, start_list, close_list, selectable
from utilities.puzzle_utilities import puzzlehash_from_string
from chiasim.hashable import Coin, Header, HeaderHash
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable.Body import Body
from .cc_wallet import CCWallet


def view_funds(wallet):
    print(f"Current balance: {str(wallet.temp_balance)}")
    print(f"UTXOs: {[x.amount for x in wallet.temp_utxos]}")


def set_name(wallet):
    selection = input("Enter a new name: ")
    wallet.set_name(selection)


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
    wallet.notify(additions, removals)


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


async def update_ledger(wallet, ledger_api, most_recent_header):
    r = await ledger_api.get_tip()
    if r['tip_hash'] != most_recent_header:
        await process_blocks(wallet,
                             ledger_api,
                             r['genesis_hash'] if most_recent_header is None else most_recent_header,
                             r['tip_hash'])
    return r['tip_hash']


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
        print(f"{selectable} q: Quit")
        print(close_list)
        selection = input(prompt)
        if selection == "1":
            r = await make_payment(wallet, ledger_api)
        elif selection == "2":
            most_recent_header = await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "3":
            most_recent_header = await farm_block(wallet, ledger_api, most_recent_header)
        elif selection == "4":
            print_my_details(wallet)
        elif selection == "5":
            set_name(wallet)


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
