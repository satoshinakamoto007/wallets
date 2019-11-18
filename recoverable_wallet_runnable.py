import asyncio
from wallet.recoverable_wallet import RecoverableWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin, Header, HeaderHash, Body
from chiasim.hashable import ProgramHash
from decimal import Decimal
from pprint import pprint


def view_coins(wallet):
    pprint([coin for coin in wallet.my_utxos])
    print('Total value: ' + str(sum([coin.amount for coin in wallet.my_utxos])))


def generate_puzzlehash(wallet):
    print('Puzzle Hash: ' + str(wallet.get_new_puzzlehash()))


async def spend_coins(wallet, ledger_api):
    amount = -1
    if wallet.current_balance <= 0:
        print('Insufficient funds')
        return None
    puzzlehash_string = input('Enter PuzzleHash: ')
    puzzlehash = ProgramHash.from_bytes(bytes.fromhex(puzzlehash_string))

    while amount > wallet.current_balance or amount < 0:
        amount = int(input('Amount: '))
    tx = wallet.generate_signed_transaction(amount, puzzlehash)
    if tx is not None:
        await ledger_api.push_tx(tx=tx)


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
    print(f'additions: {additions}')
    print(f'removals: {removals}')

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


def print_backup(wallet):
    print(f'HD Public Key: {wallet.get_recovery_public_key().serialize().hex()}\n'
          f'Private Key: {wallet.get_recovery_private_key().serialize().hex()}\n')


async def restore(ledger_api, wallet):
    root_public_key = bytes.fromhex(input('Enter the HD public key of the wallet to be restored: '))

    r = await ledger_api.all_unspents()
    recoverable_coins = []
    print('scanning', end='')
    for ptr in r['unspents']:
        print('.', end='')
        coin = await ptr.obj(data_source=ledger_api)
        if wallet.can_generate_puzzle_hash_with_root_public_key(coin.puzzle_hash, root_public_key):
            recoverable_coins.append(coin)
            print('*', end='')
    recoverable_amount = sum([coin.amount for coin in recoverable_coins])
    print(f'\nFound {len(recoverable_coins)} coins totaling {recoverable_amount}')
    stake_amount = round(recoverable_amount * (1.1 - 1))
    if wallet.current_balance < stake_amount:
        print(f'Insufficient funds to stake the recovery process. {stake_amount} needed.')
        return
    for coin in recoverable_coins:
        print('amount ', coin.amount)
        pubkey = wallet.find_pubkey_for_hash(coin.puzzle_hash, root_public_key, Decimal('1.1'))
        signed_transaction, destination_puzzlehash, amount = wallet.generate_signed_recovery_transaction(coin, root_public_key, pubkey, Decimal('1.1'))
        for coin_solution in signed_transaction.coin_solutions:
            print(f'burning {coin_solution.coin}')
            coin_solution
        child = Coin(coin.name(), destination_puzzlehash, amount)
        wallet.escrow_coins.add(child)
        await ledger_api.push_tx(tx=signed_transaction)


def view_escrow_coins(wallet):
    pprint([coin for coin in wallet.escrow_coins])
    print('Total value: ' + str(sum([coin.amount for coin in wallet.escrow_coins])))


async def grab(ledger_api, wallet):
    private_key = bytes.fromhex(input('Enter the private key of the wallet to be restored: '))
    spends = wallet.generate_recovery_transaction(wallet.escrow_coins)


async def main():
    ledger_api = await connect_to_ledger_sim('localhost', 9868)
    wallet = RecoverableWallet()
    most_recent_header = None
    selection = ''
    while selection != 'q':
        print('\nAvailable commands:')
        print('1: View Coins')
        print('2: Spend Coins')
        print('3: Get Updates')
        print('4: Farm Block')
        print('5: Generate Puzzle Hash')
        print('6: Print Backup')
        print('7: Recover Coins')
        print('8: View Escrowed Coins')
        print('9: Grab')
        print('q: Quit')
        selection = input()
        if selection == '1':
            view_coins(wallet)
        elif selection == '2':
            await spend_coins(wallet, ledger_api)
        elif selection == '3':
            most_recent_header = await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == '4':
            most_recent_header = await farm_block(wallet, ledger_api, most_recent_header)
        elif selection == '5':
            generate_puzzlehash(wallet)
        elif selection == '6':
            print_backup(wallet)
        elif selection == '7':
            await restore(ledger_api, wallet)
        elif selection == '8':
            view_escrow_coins(wallet)
        elif selection == '9':
            await grab(ledger_api, wallet)



run = asyncio.get_event_loop().run_until_complete
run(main())