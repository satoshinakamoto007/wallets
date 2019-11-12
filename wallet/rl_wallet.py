from chiasim.atoms import hexbytes

from .wallet import Wallet
import hashlib
import clvm
import sys
from chiasim.hashable import Program, ProgramHash, CoinSolution, SpendBundle, BLSSignature
from binascii import hexlify
from chiasim.validation.Conditions import (
    conditions_by_opcode, make_create_coin_condition, make_assert_my_coin_id_condition, make_assert_min_time_condition
)
from chiasim.hashable.Coin import Coin
from chiasim.hashable.CoinSolution import CoinSolutionList
from clvm_tools import binutils
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from chiasim.validation.consensus import (
    conditions_for_solution, hash_key_pairs_for_conditions_dict
)
from .puzzle_utilities import pubkey_format, puzzlehash_from_string, BLSSignature_from_string
from blspy import Signature
from .keys import build_spend_bundle, sign_f_for_keychain


# ASWallet is subclass of Wallet
class RLWallet(Wallet):
    def __init__(self):
        self.rl_coin = None
        self.interval = 0
        self.limit = 0
        super().__init__()
        return

    def notify(self, additions, deletions):
        for coin in additions:
            print(coin)
            if self.can_generate_puzzle_hash(coin.puzzle_hash):
                self.current_balance += coin.amount
                self.my_utxos.add(coin)
                self.rl_coin = coin
        for coin in deletions:
            if coin in self.my_utxos:
                self.my_utxos.remove(coin),
                self.current_balance -= coin.amount

        self.temp_utxos = self.my_utxos.copy()
        self.temp_balance = self.current_balance

    def can_generate_puzzle_hash(self, hash):
        return any(map(lambda child: hash == ProgramHash(self.rl_puzzle_for_pk(
            self.extended_secret_key.public_child(child).get_public_key().serialize(), self.limit, self.interval)),
            reversed(range(self.next_address))))


    # Solution to this puzzle must be in format: ()
    def rl_puzzle_for_pk(self, pubkey, rate_amount=None, interval_time=None):

        hex_pk = hexbytes(pubkey)
        opcode_aggsig = hexlify(ConditionOpcode.AGG_SIG).decode('ascii')
        #opcode_coin_block_age = hexlify(ConditionOpcode.ASSERT_BLOCK_AGE).decode('ascii')
        opcode_coin_block_age = hexlify(bytes([56])).decode('ascii')
        opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode('ascii')
        opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode('ascii')

        # M - chia_per_interval
        # N - interval_blocks
        # V - amount being spent
        # MIN_BLOCK_AGE = V / (M / N)
        # if not (min_block_age * M = 1000 * N) do X (raise)
        # improve once > operator becomes available
        # ASSERT_COIN_BLOCK_AGE_EXCEEDS min_block_age
        #TODO add TEMPLATE_BLOCK_AGE to WHOLE_PUZZLE once ASSERT_COIN_BLOCK_AGE_EXCEEDS becomes available

        TEMPLATE_BLOCK_AGE = f"(i (= (* (f (r (r (r (r (r (a))))))) (q {interval_time})) (* (f (r (r (r (r (a)))))) (q {rate_amount}))) (c (q 0x{opcode_coin_block_age}) (c (f (r (r (r (r (r (a))))))) (q ()))) (q (x (q \"wrong min block time\"))))"
        TEMPLATE_MY_ID = f"(c (q 0x{opcode_myid}) (c (sha256 (f (a)) (f (r (a))) (uint64 (f (r (r (a)))))) (q ())))"
        CREATE_CHANGE = f"(c (q 0x{opcode_create}) (c (f (r (a))) (c (- (f (r (r (a)))) (f (r (r (r (r (a))))))) (q ()))))"
        AGGSIG_ENTIRE_SOLUTION = f"(c (q 0x{opcode_aggsig}) (c (q 0x{hex_pk}) (c (sha256 (wrap (a))) (q ()))))"
        CREATE_NEW_COIN = f"(c (q 0x{opcode_create}) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (q ()))))"

        WHOLE_PUZZLE = f"(c {CREATE_CHANGE} (c {AGGSIG_ENTIRE_SOLUTION} (c {TEMPLATE_MY_ID} (c {CREATE_NEW_COIN} (q ())))))"

        return Program(binutils.assemble(WHOLE_PUZZLE))

    # Solution to this puzzle needs (self_coin_id, self_puzzlehash, self_amount, (new_puzzle_hash, amount))
    # min block time = (new_amount * self.interval) / self.rate
    def solution_for_rl(self, my_coin_id, my_puzzlehash, my_amount, new_puzzlehash, new_amount, min_block_height):
        solution = f"(0x{my_coin_id} 0x{my_puzzlehash} {my_amount} 0x{new_puzzlehash} {new_amount} {min_block_height})"
        return Program(binutils.assemble(solution))

    def get_keys(self, hash):
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hash == ProgramHash(self.rl_puzzle_for_pk(pubkey.serialize())):
                return pubkey, self.extended_secret_key.private_child(child).get_private_key()

    # This is for sending a received RL coin, not creating a new RL coin
    def rl_generate_unsigned_transaction(self, to_puzzlehash, amount):
        # we only have/need one coin in this wallet at any time - this code can be improved
        spends = []
        coin = self.rl_coin
        puzzle_hash = coin.puzzle_hash

        pubkey, secretkey = self.get_keys(puzzle_hash)
        puzzle = self.rl_puzzle_for_pk(pubkey.serialize(), self.limit, self.interval)
        solution = self.solution_for_rl(coin.parent_coin_info, puzzle_hash, coin.amount, to_puzzlehash, amount, 100)

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def rl_generate_signed_transaction(self, to_puzzle_hash, amount):

        if amount > self.rl_coin.amount:
            return None

        change = self.rl_coin.amount - amount
        transaction = self.rl_generate_unsigned_transaction(
            to_puzzle_hash, amount)
        self.temp_coin = Coin(self.rl_coin, self.rl_coin.puzzle_hash,
                              change)
        return self.rl_sign_transaction(transaction)

    # TODO track self.rl_coin blockage and calculate available spend amount
    def rl_balance(self):
        total_amount = rl_coin.amount
        available_amount = 0
        return total_amount, available_amount

    def rl_sign_transaction(self, spends: (Program, [CoinSolution])):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = self.get_keys(
                solution.coin.puzzle_hash)
            secretkey = BLSPrivateKey(secretkey)
            signature = secretkey.sign(
                ProgramHash(Program(solution.solution.code)))
            sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = CoinSolutionList(
            [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle.code, coin_solution.solution.code])) for
             (puzzle, coin_solution) in spends])
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def get_new_puzzle(self):
        pubkey = self.get_next_public_key().serialize()
        puzzle = puzzle_for_pk(pubkey)
        return puzzle

    def get_new_puzzlehash(self):
        puzzle = self.get_new_puzzle()
        puzzlehash = ProgramHash(puzzle)
        return puzzlehash
