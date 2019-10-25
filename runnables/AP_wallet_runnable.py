from decorations import print_leaf, divider, prompt, start_list, close_list, selectable, informative
from wallet.ap_wallet import APWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin
from chiasim.hashable.Body import BodyList
from chiasim.puzzles.puzzle_utilities import pubkey_format, puzzlehash_from_string, BLSSignature_from_string
from binascii import hexlify
from runnables.wallet_runnable import Runnable


class AP_Runnable(Runnable):

    def view_funds(wallet):
        print(divider)
        if wallet.temp_coin is not None:
            print(wallet.temp_coin.amount)
        else:
            print([x.amount for x in wallet.my_utxos])

    def add_contact(wallet, approved_puzhash_sig_pairs):
        choice = "c"
        print(divider)
        while choice == "c":
            singlestring = input("Enter contact info string: ")
            arr = singlestring.split(":")
            name = arr[0]
            puzzle = arr[1]
            puzhash = puzzlehash_from_string(puzzle)
            sig = arr[2]
            signature = BLSSignature_from_string(sig)
            while name in approved_puzhash_sig_pairs:
                print(name + " is already a contact. Would you like to add a new contact or overwrite " + name + "?")
                print(selectable + " 1: Overwrite")
                print(selectable + " 2: Add new contact")
                print(selectable + " q: Return to menu")
                pick = input(prompt)
                if pick == "q":
                    return
                elif pick == "1":
                    continue
                elif pick == "2":
                    name = input("Enter new name for contact: ")
            approved_puzhash_sig_pairs[name] = (puzhash, signature)
            choice = input("Press 'c' to add another, or 'q' to return to menu: ")

    def view_contacts(approved_puzhash_sig_pairs):
        for name in approved_puzhash_sig_pairs:
            print(" - " + name)

    def print_my_details(wallet):
        print(divider)
        print(informative + "Name: " + wallet.name)
        if wallet.puzzle_generator_id == "1ea50e9399e360c85c240e9d17c5d11ccb8fbf37b0ee6e551282ddd5b5613206":
            print("Awaiting initial coin...")
        else:
            print(informative + "Puzzle Generator: ")
            print(wallet.puzzle_generator)
            print(informative +  "Generator hash identifier:")
            print(wallet.puzzle_generator_id)
        pubkey = hexlify(wallet.get_next_public_key().serialize()).decode('ascii')
        print(informative + "New pubkey: " + pubkey)
        print(informative + "Single string: " + wallet.name + ":" +
              wallet.puzzle_generator_id + ":" + pubkey)

    def make_payment(wallet, approved_puzhash_sig_pairs):
        amount = -1
        if wallet.current_balance <= 0:
            print("You need some money first")
            return
        print(start_list)
        print("Select a contact from approved list: ")
        for name in approved_puzhash_sig_pairs:
            print(" - " + name)
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

    async def update_ledger(wallet, ledger_api, most_recent_header):
        if most_recent_header is None:
            r = await ledger_api.get_all_blocks()
        else:
            r = await ledger_api.get_recent_blocks(most_recent_header=most_recent_header)
        update_list = BodyList.from_bin(r)
        for body in update_list:
            additions = list(additions_for_body(body))
            print(additions)
            removals = removals_for_body(body)
            removals = [Coin.from_bin(await ledger_api.hash_preimage(hash=x)) for x in removals]
            spend_bundle_list = wallet.notify(additions, removals)
            #breakpoint()
            if spend_bundle_list is not None:
                for spend_bundle in spend_bundle_list:
                    #breakpoint()
                    _ = await ledger_api.push_tx(tx=spend_bundle)

    def ap_settings(wallet, approved_puzhash_sig_pairs):
        print(divider)
        print(selectable + " 1: Add Authorised Payee")
        print(selectable + " 2: Change initialisation settings")
        print("WARNING: This is only for if you messed it up the first time.")
        print("Press 'c' to continue or any other key to return")
        choice = input(prompt)
        if choice != "c":
            return
        print("Your pubkey is: " + pubkey_format(wallet.get_next_public_key()))
        print("Please fill in some initialisation information (this can be changed later)")
        print("Please enter initialisation string: ")
        init_string = input(prompt)
        arr = init_string.split(":")
        AP_puzzlehash = arr[0]
        a_pubkey = arr[1]
        wallet.set_sender_values(AP_puzzlehash, a_pubkey)
        sig = BLSSignature_from_string(arr[2])
        wallet.set_approved_change_signature(sig)

    async def main(self):
        ledger_api = await connect_to_ledger_sim("localhost", 9868)
        selection = ""
        wallet = APWallet()
        approved_puzhash_sig_pairs = {}  # 'name': (puzhash, signature)
        most_recent_header = None
        print(divider)
        print_leaf()
        print(divider)
        print("Welcome to AP Wallet")
        print("Your pubkey is: " +
              hexlify(wallet.get_next_public_key().serialize()).decode('ascii'))
        print("Please fill in some initialisation information (this can be changed later)")
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

        while selection != "q":
            print(divider)
            print(start_list)
            print("Select a function:")
            print(selectable + " 1: View Funds")
            print(selectable + " 2: Add Payee")
            print(selectable + " 3: Make Payment")
            print(selectable + " 4: View Payees")
            print(selectable + " 5: Get Update")
            print(selectable + " 6: *GOD MODE* Commit Block / Get Money")
            print(selectable + " 7: Print my details for somebody else")
            print(selectable + " 8: Set my wallet detail")
            print(selectable + " 9: Make QR code")
            print(selectable + " 10: AP Settings")
            print(selectable + " q: Quit")
            print(close_list)
            selection = input(prompt)
            if selection == "1":
                self.view_funds(wallet)
            elif selection == "2":
                self.add_contact(wallet, approved_puzhash_sig_pairs)
            elif selection == "3":
                r = self.make_payment(wallet, approved_puzhash_sig_pairs)
                if r is not None:
                    await ledger_api.push_tx(tx=r)
            elif selection == "4":
                self.view_contacts(approved_puzhash_sig_pairs)
            elif selection == "5":
                await self.update_ledger(wallet, ledger_api, most_recent_header)
            elif selection == "6":
                most_recent_header = await self.new_block(wallet, ledger_api)
            elif selection == "7":
                self.print_my_details(wallet)
            elif selection == "8":
                self.set_name(wallet)
            elif selection == "9":
                self.make_QR(wallet)
            elif selection == "10":
                self.ap_settings(wallet, approved_puzhash_sig_pairs)
