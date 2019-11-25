import asyncio
from wallet.recoverable_wallet import RecoverableWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin, Header, HeaderHash, Body
from chiasim.hashable import ProgramHash
from chiasim.remote.client import RemoteError
from decimal import Decimal
from blspy import ExtendedPublicKey, PrivateKey


def view_coins(wallet):
    for coin in wallet.my_utxos:
        print(f'{coin.name()}: {coin.amount}')
    print('Total value: ' + str(wallet.balance()))


def generate_puzzlehash(wallet):
    print('Puzzle Hash: ' + str(wallet.get_new_puzzlehash()))


async def spend_coins(wallet, ledger_api):
    puzzlehash_string = input('Enter PuzzleHash: ')
    puzzlehash = ProgramHash.from_bytes(bytes.fromhex(puzzlehash_string))
    amount = int(input('Amount: '))
    if amount > wallet.current_balance or amount < 0:
        print('Insufficient funds')
        return None
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
    wallet.notify(additions, removals)
    clawback_coins = [coin for coin in additions if wallet.is_in_escrow(coin)]
    if len(clawback_coins) != 0:
        print(f'WARNING! Coins from this wallet have been moved to escrow!\n'
              f'Attempting to send a clawback for these coins:\n')
        for coin in clawback_coins:
            print(f'{coin.name()}: {coin.amount}')
        transaction = wallet.generate_clawback_transaction(clawback_coins)
        await ledger_api.push_tx(tx=transaction)
        print('Clawback transaction submitted')


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
    print(f'HD Root Public Key: {wallet.get_recovery_hd_root_public_key().serialize().hex()}\n'
          f'Secret Key: {wallet.get_recovery_private_key().serialize().hex()}\n')


async def restore(ledger_api, wallet):
    root_public_key = bytes.fromhex(input('Enter the HD public key of the wallet to be restored: '))
    recovery_pubkey = ExtendedPublicKey.from_bytes(root_public_key).public_child(0).get_public_key().serialize()
    r = await ledger_api.all_unspents()
    recoverable_coins = []
    print('scanning', end='')
    for ptr in r['unspents']:
        coin = await ptr.obj(data_source=ledger_api)
        if wallet.can_generate_puzzle_hash_with_root_public_key(coin.puzzle_hash, root_public_key):
            recoverable_coins.append(coin)
            print('*', end='', flush=True)
        else:
            print('.', end='', flush=True)
    recoverable_amount = sum([coin.amount for coin in recoverable_coins])
    print(f'\nFound {len(recoverable_coins)} coins totaling {recoverable_amount}')
    stake_amount = round(recoverable_amount * (1.1 - 1))
    if wallet.current_balance < stake_amount:
        print(f'Insufficient funds to stake the recovery process. {stake_amount} needed.')
        return
    for coin in recoverable_coins:
        print(f'{coin.name()}: {coin.amount}')
        pubkey = wallet.find_pubkey_for_hash(coin.puzzle_hash, root_public_key, Decimal('1.1'))
        signed_transaction, destination_puzzlehash, amount = \
            wallet.generate_signed_recovery_to_escrow_transaction(coin, recovery_pubkey, pubkey, Decimal('1.1'))
        child = Coin(coin.name(), destination_puzzlehash, amount)
        wallet.escrow_coins.add(child)
        await ledger_api.push_tx(tx=signed_transaction)


def view_escrow_coins(wallet):
    for coin in wallet.escrow_coins:
        print(f'{coin.name()}: {coin.amount}')
    print('Total value: ' + str(sum([coin.amount for coin in wallet.escrow_coins])))


async def recover_escrow_coins(ledger_api, wallet):
    root_public_key_serialized = bytes.fromhex(input('Enter the HD Root Public key of the wallet to be restored: '))
    root_public_key = ExtendedPublicKey.from_bytes(root_public_key_serialized)
    secret_key_serialized = bytes.fromhex(input('Enter the Secret Key of the wallet to be restored: '))
    secret_key = PrivateKey.from_bytes(secret_key_serialized)
    signed_transaction = wallet.generate_recovery_transaction(wallet.escrow_coins, root_public_key, secret_key)
    r = await ledger_api.push_tx(tx=signed_transaction)
    if type(r) is RemoteError:
        print('Too soon to recover coins')
    else:
        print('Recovery transaction submitted')


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
        print('8: View Escrow Coins')
        print('9: Recover Escrow Coins')
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
            await recover_escrow_coins(ledger_api, wallet)



run = asyncio.get_event_loop().run_until_complete
run(main())