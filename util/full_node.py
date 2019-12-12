import asyncio

from chiasim.clients import ledger_sim
from chiasim.hashable import Body, Header, HeaderHash
from chiasim.remote.client import request_response_proxy
from chiasim.validation.chainview import apply_deltas
from chiasim.wallet.deltas import additions_for_body, removals_for_body


async def ledger_sim_proxy():
    """
    Return an async proxy to the ledger sim instance running on 9868.
    """
    reader, writer = await asyncio.open_connection(host="localhost", port=9868)
    proxy = request_response_proxy(reader, writer, ledger_sim.REMOTE_SIGNATURES)
    return proxy


async def generate_coins(full_node, coinbase_puzzle_hash, fees_puzzle_hash):
    await full_node.next_block(
        coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash
    )


async def sync(storage, full_node):
    """
    Get blocks from ledger sim and make a note of new and spent coins
    that are "interesting".
    """
    headers = []
    tip_dict = await full_node.get_tip()
    genesis_hash = tip_dict["genesis_hash"]
    header_hash = tip_dict["tip_hash"]
    header_index = tip_dict["tip_index"]
    while True:
        if header_hash == genesis_hash:
            break
        if len(storage._header_list) >= header_index and header_hash == HeaderHash(
            storage._header_list[header_index - 1]
        ):
            break
        preimage = await full_node.hash_preimage(hash=header_hash)
        header = Header.from_bytes(preimage)
        headers.append(header)
        header_hash = header.previous_hash
        header_index -= 1
    await storage.rollback_to_block(header_index)
    new_block_count = len(headers)
    while headers:
        header = headers.pop()
        preimage = await full_node.hash_preimage(hash=header.body_hash)
        body = Body.from_bytes(preimage)
        additions = [
            _
            for _ in additions_for_body(body)
            if _.puzzle_hash in storage._interested_puzzled_hashes
        ]
        removals = [
            _
            for _ in removals_for_body(body)
            if _ in storage._interested_puzzled_hashes
        ]
        await apply_deltas(header_index, additions, removals, storage, storage)
        storage._header_list.append(header)
        header_index += 1
    return new_block_count
