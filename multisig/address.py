def address_for_puzzle_hash(puzzle_hash):
    return puzzle_hash.hex()


def puzzle_hash_for_address(address):
    return bytes.fromhex(address)
