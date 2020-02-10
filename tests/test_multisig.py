import asyncio
import pathlib
import tempfile
from aiter import map_aiter

from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter

from multisig.address import puzzle_hash_for_address
from multisig.pst import PartiallySignedTransaction
from multisig.signer import generate_signatures
from multisig.storage import Storage
from multisig.wallet import spend_coin, finalize_pst, main_loop, all_coins_and_unspents
from multisig.wallet import MultisigHDWallet

from utilities.BLSHDKey import BLSPrivateHDKey


async def proxy_for_unix_connection(path):
    reader, writer = await asyncio.open_unix_connection(path)
    return request_response_proxy(reader, writer, ledger_sim.REMOTE_SIGNATURES)


def make_client_server():
    init_logging()
    run = asyncio.get_event_loop().run_until_complete
    path = pathlib.Path(tempfile.mkdtemp(), "port")
    server, aiter = run(start_unix_server_aiter(path))
    rws_aiter = map_aiter(
        lambda rw: dict(reader=rw[0], writer=rw[1], server=server), aiter
    )
    initial_block_hash = bytes(([0] * 31) + [1])
    ledger = ledger_api.LedgerAPI(initial_block_hash, RAM_DB())
    server_task = asyncio.ensure_future(api_server(rws_aiter, ledger))
    remote = run(proxy_for_unix_connection(path))
    # make sure server_task isn't garbage collected
    remote.server_task = server_task
    return remote


async def coin_for_address(remote, address):
    puzzle_hash = puzzle_hash_for_address(address)
    r = await remote.next_block(
        coinbase_puzzle_hash=puzzle_hash, fees_puzzle_hash=puzzle_hash
    )
    body = r["body"]
    return body.coinbase_coin


def create_wallet(M, N):
    private_wallets = [BLSPrivateHDKey.from_seed(b"%d" % _) for _ in range(N)]
    pub_hd_keys = [_.public_hd_key() for _ in private_wallets]
    wallet = MultisigHDWallet(M, pub_hd_keys)
    return wallet, private_wallets


def test_pst_serialization():
    run = asyncio.get_event_loop().run_until_complete

    remote = make_client_server()

    index = 0
    wallet, private_wallets = create_wallet(2, 5)
    address = wallet.address_for_index(index)
    coin = run(coin_for_address(remote, address))

    dest_address = wallet.address_for_index(10)
    pst = spend_coin(wallet, [coin], dest_address)

    # serialize and deserialize the pst
    pst_blob = bytes(pst)
    pst_1 = PartiallySignedTransaction.from_bytes(pst_blob)
    assert pst == pst_1
    assert bytes(pst) == bytes(pst_1)


def test_multisig_spend():
    remote = make_client_server()

    run = asyncio.get_event_loop().run_until_complete

    M, N = 2, 5
    wallet, private_wallets = create_wallet(M, N)

    index = 0
    address = wallet.address_for_index(index)
    assert address == "a8f583e8f09c8eeca04c4b62f34734fb3747b021eb41ed05e8265d9dd396cbf6"

    coin = run(coin_for_address(remote, address))

    dest_address = wallet.address_for_index(100)
    pst = spend_coin(wallet, [coin], dest_address)

    # sign the pst

    sigs = []
    for pw in private_wallets[:M]:
        sigs.extend(generate_signatures(pst, pw))

    spend_bundle, summary_list = finalize_pst(wallet, pst, sigs)

    r = run(remote.push_tx(tx=spend_bundle))
    assert r["response"].startswith("accepted SpendBundle")


def test_multisig_spend_two():
    remote = make_client_server()

    run = asyncio.get_event_loop().run_until_complete

    M, N = 2, 5
    wallet, private_wallets = create_wallet(M, N)

    index = 0
    address = wallet.address_for_index(index)
    assert address == "a8f583e8f09c8eeca04c4b62f34734fb3747b021eb41ed05e8265d9dd396cbf6"

    coin_0 = run(coin_for_address(remote, address))

    index = 1
    address = wallet.address_for_index(index)
    assert address == "f29cfc4cfdea7f7d2692dc08e670e46bbd73a1fbef114df2c9def81a9ecde945"

    coin_1 = run(coin_for_address(remote, address))

    dest_address = wallet.address_for_index(100)
    pst = spend_coin(wallet, [coin_0, coin_1], dest_address)

    # sign the pst

    sigs = []
    for pw in private_wallets[:M]:
        sigs.extend(generate_signatures(pst, pw))

    spend_bundle, summary_list = finalize_pst(wallet, pst, sigs)

    r = run(remote.push_tx(tx=spend_bundle))
    assert r["response"].startswith("accepted SpendBundle")


def input_for(strings):
    def my_input(*args):
        nonlocal strings
        if len(strings) == 0:
            raise EOFError
        r, strings[:] = strings[0], strings[1:]
        print("%s%s" % (args[0], r))
        return r

    return my_input


def test_ui_process():
    from multisig.wallet import load_wallet

    from pathlib import Path

    run = asyncio.get_event_loop().run_until_complete

    PATH = Path(tempfile.mktemp())
    remote = make_client_server()

    storage = Storage("junk path", remote)

    # create the wallet

    # these keys are based on extended private keys that serialize as
    # "0000000100000000000000000050421bbc044a3cfcd2297e5bb799a4c5e79069cd1df416acdc3"
    # "108d7575346890bf96618a62dd6f69b921b8ef3ef8f6a5b39ccb23162d81bd49758c0e3ff238b"
    #
    # "00000001000000000000000000058c016b8e4e3b92a41814f758b500d1f6d4df070466a737e08"
    # "a330979a78ee6584e7593ea0a6e0f1288db16b1bd97394d2e21453c9b8c0c89e5fcca01089ada"
    #
    # "0000000100000000000000000027d28a4ab48580acaf9c4dc48bf72020b2cc9a7394fe507653d"
    # "255a9ceeed83867cd6ee2839495345c0430293af8cbc72e715576f852219c32a8fb047c6d88b0"

    CREATE_WALLET_INPUTS = [
        "0000000100000000000000000050421bbc044a3cfcd2297e5bb799a4c5e79069cd1df416acdc3108d75753468908e5b516e93868159d0eb07aab715805acce775a55e7702968490893d73f644619e6e9ff0b95c6315b1e895544edd94a",
        "00000001000000000000000000058c016b8e4e3b92a41814f758b500d1f6d4df070466a737e08a330979a78ee614a963ec636d0ce1577980e705a24bf4bcb928a8577d9e66c716b37dcf444b0e624d022b59fdcfe3092333153906091c",
        "0000000100000000000000000027d28a4ab48580acaf9c4dc48bf72020b2cc9a7394fe507653d255a9ceeed8381831c6add059b99565996fa80f4799c1b1a37eae6a1855678b14ac77012e423d5a3a935df5d495954112d0f275ad091b",
        "",
        "2",
        "q",
    ]
    run(main_loop(PATH, storage=storage, input=input_for(CREATE_WALLET_INPUTS)))
    wallet = load_wallet(PATH)

    assert (
        wallet.address_for_index(0)
        == "332298d6fb67ca29e1c15f26a4cc4b655ecc8c85135909b23e2fa9fa8a341d06"
    )

    GENERATE_ADDRESS_INPUTS = [
        "1",  # generate address
        "10",
        "y",
        "q",
    ]

    run(main_loop(PATH, storage=storage, input=input_for(GENERATE_ADDRESS_INPUTS)))

    coins, unspents = run(all_coins_and_unspents(storage))
    SPEND_COIN_INPUTS = [
        "3",
        "2",
        coins[0].name().hex(),
        coins[1].name().hex(),
        "",
        "42cd0487d583c348229d1de188e8523ab814a808435bf61e1f27f81775197339d72117d870bc421d64244ac5c0440105076a40c385907a920fae054b683874a81d5adcc64cb4d70afc27f4b4ab83e4830597d5a272cf9f9056d9d19357d5bc8c",
        "4917f65ce8d46c3b14fb32ae9d1202b48b12770ab52d0dda33c896f9442cc8c26c978c257a354667c0bcd7160f7b5b24117a7a3b102f0ccb1d06a2069d28474e1ead4eae0c86d449ff95404241a413d893f97fe7e6a745f1078dc1516634f916",
        "y",
        "q",
    ]

    run(main_loop(PATH, storage=storage, input=input_for(SPEND_COIN_INPUTS)))
