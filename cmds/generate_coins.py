import argparse
import asyncio


from util.address import puzzle_hash_for_address
from util.full_node import ledger_sim_proxy, generate_coins


DEFAULT_PUZZLE_HASH = bytes([0] * 32)


def create_parser():

    parser = argparse.ArgumentParser(
        description="Create seed coins for a given address in ledger-sim."
    )

    parser.add_argument(
        "-f",
        "--fee-address",
        help="Address to use for the block fees",
        type=puzzle_hash_for_address,
        required=False,
        default=DEFAULT_PUZZLE_HASH,
    )

    parser.add_argument(
        "reward_address",
        help="Address to use for the block reward",
        type=puzzle_hash_for_address,
    )

    return parser


async def do_generate_coins(args, parser):
    full_node = await ledger_sim_proxy()
    await generate_coins(full_node, args.reward_address, args.fee_address)


def main():
    parser = create_parser()
    args = parser.parse_args()
    asyncio.get_event_loop().run_until_complete(do_generate_coins(args, parser))


if __name__ == "__main__":
    main()
