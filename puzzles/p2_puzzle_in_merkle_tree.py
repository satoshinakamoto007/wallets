"""
Pay to puzzle hash in a merkle tree

In this puzzle program, there is a binary tree of depth N
containing K <= 2^N puzzles. We reveal a path to one of them,
and then solve it.



This roughly corresponds to bitcoin's MAST.
"""

from clvm_tools import binutils

from chiasim.atoms import hexbytes
from chiasim.hashable import Program


def position_to_index(position, depth):
    s = bin(position)[2:]
    s += ("0" * depth) + s
    s = s[-depth:]
    s = "".join(list(reversed(s)))
    return int(s, 2)


def solution_tree_for_position(tree, position, hash_f):
    if isinstance(tree, bytes):
        return tree
    next_position = position >> 1
    if next_position + next_position != position:
        left = hash_tree(tree[0], hash_f)
        right = solution_tree_for_position(tree[1], position >> 1, hash_f)
    else:
        left = solution_tree_for_position(tree[0], position >> 1, hash_f)
        right = hash_tree(tree[1], hash_f)
    return (left, right)


def list_to_tree(items):
    size = len(items)
    if size == 1:
        return items[0], 0
    if size & 1:
        items.append(items[-1])
        size += 1
    halfway_index = size >> 1
    left_node, left_height = list_to_tree(items[:halfway_index])
    right_node, right_height = list_to_tree(items[halfway_index:])
    return (left_node, right_node), max(left_height, right_height) + 1


def hash_tree(tree, hash_f):
    if isinstance(tree, bytes):
        return tree
    left = hash_tree(tree[0], hash_f)
    right = hash_tree(tree[1], hash_f)
    return hash_f(left + right)


def puzzle_for_tree_hash(tree_hash):
    TEMPLATE = """
        (q 0x%s)
    """
    return Program(binutils.assemble(TEMPLATE % hexbytes(tree_hash)))


def puzzle_for_puzzle_hashes(puzzle_hash_list):
    tree, levels = list_to_tree(puzzle_hash_list)
    top_level_hash = hash_tree(tree)
    return puzzle_for_tree_hash(top_level_hash)


def solution_for_position(solution_tree, puzzle_reveal, solution):
    pass


def is_in_tree(v, tree):
    if isinstance(tree, bytes):
        return v == tree
    return any(is_in_tree(v, tree[_]) for _ in [0, 1])


def main():
    from chiasim.hashable.Hash import std_hash

    COUNT = 61
    hashes = [std_hash(_.to_bytes(8, "big")) for _ in range(COUNT)]
    breakpoint()
    tree, depth = list_to_tree(hashes)
    print(tree)
    the_hash = hash_tree(tree, std_hash)
    print(the_hash)
    for _ in range(COUNT):
        index = position_to_index(_, depth)
        subtree = solution_tree_for_position(tree, index, std_hash)
        print("looking for %s" % hashes[_])
        print("%d [%d]: %s\n" % (_, index, subtree))
        solution_hash = hash_tree(subtree, std_hash)
        assert solution_hash == the_hash
        assert is_in_tree(hashes[_], subtree)


if __name__ == "__main__":
    main()
