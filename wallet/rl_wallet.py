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
import math

# RLWallet is subclass of Wallet
class RLWallet(Wallet):
    def __init__(self):
        self.aggregation_coins = set()
        self.RL_puzzlehash = None
        self.rl_coin = None
        self.interval = 0
        self.limit = 0
        super().__init__()
        return

    def notify(self, additions, deletions):
        for coin in additions:
            if self.can_generate_puzzle_hash(coin.puzzle_hash):
                self.current_balance += coin.amount
                self.my_utxos.add(coin)
                self.rl_coin = coin
                print("\nNOTIFY COIN: ",coin)
        for coin in deletions:
            if coin in self.my_utxos:
                self.my_utxos.remove(coin),
                self.current_balance -= coin.amount

        self.temp_utxos = self.my_utxos.copy()
        self.temp_balance = self.current_balance
        spend_bundle_list = self.ac_notify(additions)
        return spend_bundle_list

    def ac_notify(self, additions):
        if len(self.my_utxos) >= 1:
            self.rl_coin = self.my_utxos.copy().pop()  # reset temp_coin
        else:
            return  # prevent unnecessary searching
        spend_bundle_list = []

        for coin in additions:
            my_utxos_copy = self.my_utxos.copy()
            for mycoin in self.my_utxos:
                # Check if we have already spent any coins in our utxo set
                if coin.parent_coin_info == mycoin.name():
                    my_utxos_copy.remove(mycoin)
                    self.current_balance -= mycoin.amount
                    self.my_utxos = my_utxos_copy.copy()
                    self.rl_coin = my_utxos_copy.copy().pop()
                    print("\nNew coin!!!!")

            if ProgramHash(self.rl_make_aggregation_puzzle(self.rl_coin.puzzle_hash)) == coin.puzzle_hash:
                self.aggregation_coins.add(coin)
                spend_bundle = self.rl_generate_signed_aggregation_transaction()
                spend_bundle_list.append(spend_bundle)

        if spend_bundle_list:
            return spend_bundle_list
        else:
            return None


    def can_generate_puzzle_hash(self, hash):
        return any(map(lambda child: hash == ProgramHash(self.rl_puzzle_for_pk(
            self.extended_secret_key.public_child(child).get_public_key().serialize(), self.limit, self.interval)),
            reversed(range(self.next_address))))


    # Solution to this puzzle must be in format: ()
    def rl_puzzle_for_pk(self, pubkey, rate_amount=None, interval_time=None):

        hex_pk = hexbytes(pubkey)
        opcode_aggsig = hexlify(ConditionOpcode.AGG_SIG).decode('ascii')
        opcode_coin_block_age = hexlify(ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS).decode('ascii')
        opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode('ascii')
        opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode('ascii')

        # M - chia_per_interval
        # N - interval_blocks
        # V - amount being spent
        # MIN_BLOCK_AGE = V / (M / N)
        # if not (min_block_age * M >= 1000 * N) do X (raise)
        # ASSERT_COIN_BLOCK_AGE_EXCEEDS min_block_age

        #TODO confirm parent has same puzzle hash as me or it's origin

        AGGSIG_ENTIRE_SOLUTION = f"(c (q 0x{opcode_aggsig}) (c (q 0x{hex_pk}) (c (sha256 (wrap (a))) (q ()))))"

        TEMPLATE_BLOCK_AGE = f"((c (i (i (= (* (f (r (r (r (r (r (a))))))) (q {rate_amount})) (* (f (r (r (r (r (a)))))) (q {interval_time}))) (q 1) (q (> (* (f (r (r (r (r (r (a))))))) (q {rate_amount})) (* (f (r (r (r (r (a))))))) (q {interval_time})))) (q (c (q 0x{opcode_coin_block_age}) (c (f (r (r (r (r (r (a))))))) (q ())))) (q (x (q \"wrong min block time\")))) (a) ))"
        TEMPLATE_MY_ID = f"(c (q 0x{opcode_myid}) (c (sha256 (f (a)) (f (r (a))) (uint64 (f (r (r (a)))))) (q ())))"
        CREATE_CHANGE = f"(c (q 0x{opcode_create}) (c (f (r (a))) (c (- (f (r (r (a)))) (f (r (r (r (r (a))))))) (q ()))))"
        CREATE_NEW_COIN = f"(c (q 0x{opcode_create}) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (q ()))))"
        RATE_LIMIT_PUZZLE = f"(c {TEMPLATE_BLOCK_AGE} (c {CREATE_CHANGE} (c {TEMPLATE_MY_ID} (c {CREATE_NEW_COIN} (q ())))))"

        CREATE_CONSOLIDATED = f"(c (q 0x{opcode_create}) (c (f (r (a))) (c (+ (f (r (r (r (r (a)))))) (f (r (r (r (r (r (r (a))))))))) (q ()))))"
        MODE_TWO_ME_STRING = f"(c (q 0x{opcode_myid}) (c (sha256 (f (r (r (r (r (r (a))))))) (f (r (a))) (uint64 (f (r (r (r (r (r (r (a)))))))))) (q ())))"
        CREATE_LOCK = f"(c (q 0x{opcode_create}) (c (sha256 (wrap (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256 (f (r (r (a)))) (f (r (r (r (a))))) (uint64 (f (r (r (r (r (a)))))))) (q ()))) (c (q (q ())) (q ())))) (q ()))))) (c (uint64 (q 0)) (q ()))))"
        MODE_TWO = f"(c {MODE_TWO_ME_STRING} (c {CREATE_LOCK} (c {CREATE_CONSOLIDATED} (q ()))))"

        WHOLE_PUZZLE = f"(c {AGGSIG_ENTIRE_SOLUTION} ((c (i (= (f (a)) (q 1)) (q ((c (q {RATE_LIMIT_PUZZLE}) (r (a))))) (q {MODE_TWO})) (a))) (q ()))"

        #print("\n Whole puzzle : ", WHOLE_PUZZLE)
        return Program(binutils.assemble(WHOLE_PUZZLE))


    def rl_make_aggregation_puzzle(self, wallet_puzzle):
        # If Wallet A wants to send further funds to Wallet B then they can lock them up using this code
        # Solution will be (my_id wallet_coin_primary_input wallet_coin_amount)
        opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode('ascii')
        wp = hexlify(wallet_puzzle).decode('ascii')
        opcode_consumed = hexlify(ConditionOpcode.ASSERT_COIN_CONSUMED).decode('ascii')
        me_is_my_id = f"(c (q 0x{opcode_myid}) (c (f (a)) (q ())))"

        # lock_puzzle is the hash of '(r (c (q "merge in ID") (q ())))'
        lock_puzzle = "(sha256 (wrap (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (c (q (q ())) (q ())))) (q ())))))"
        parent_coin_id = f"(sha256 (f (r (a))) (q 0x{wp}) (uint64 (f (r (r (a))))))"
        input_of_lock = f"(c (q 0x{opcode_consumed}) (c (sha256 {parent_coin_id} {lock_puzzle} (uint64 (q 0))) (q ())))"
        puz = f"(c {me_is_my_id} (c {input_of_lock} (q ())))"

        #print("\nAggregations puzzle: ", puz)
        return Program(binutils.assemble(puz))


    # Solution to this puzzle needs (self_coin_id, self_puzzlehash, self_amount, (new_puzzle_hash, amount))
    # min block time = Math.ceil((new_amount * self.interval) / self.limit)
    def solution_for_rl(self, my_coin_id, my_puzzlehash, my_amount, new_puzzlehash, new_amount):
        min_block_count = math.ceil((new_amount * self.interval) / self.limit)
        solution = f"(1 0x{my_coin_id} 0x{my_puzzlehash} {my_amount} 0x{new_puzzlehash} {new_amount} {min_block_count})"
        return Program(binutils.assemble(solution))

    def rl_make_aggregation_solution(self, myid, wallet_coin_primary_input, wallet_coin_amount):
        sol = "(0x%s 0x%s %d)" % (hexlify(myid).decode('ascii'), hexlify(
            wallet_coin_primary_input).decode('ascii'), wallet_coin_amount)
        return Program(binutils.assemble(sol))

    def rl_make_solution_mode_2(self, wallet_puzzle_hash, consolidating_primary_input, consolidating_coin_puzzle_hash, outgoing_amount, my_primary_input, incoming_amount):
        wallet_puzzle_hash = hexlify(wallet_puzzle_hash).decode('ascii')
        consolidating_primary_input = hexlify(consolidating_primary_input).decode('ascii')
        consolidating_coin_puzzle_hash = hexlify(consolidating_coin_puzzle_hash).decode('ascii')
        primary_input = hexlify(my_primary_input).decode('ascii')
        sol = f"(2 0x{wallet_puzzle_hash} 0x{consolidating_primary_input} 0x{consolidating_coin_puzzle_hash} {outgoing_amount} 0x{primary_input} {incoming_amount})"
        return Program(binutils.assemble(sol))

    def get_keys(self, hash):
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hash == ProgramHash(self.rl_puzzle_for_pk(pubkey.serialize(), self.limit, self.interval)):
                return pubkey, self.extended_secret_key.private_child(child).get_private_key()

    # This is for sending a received RL coin, not creating a new RL coin
    def rl_generate_unsigned_transaction(self, to_puzzlehash, amount):
        # we only have/need one coin in this wallet at any time - this code can be improved
        spends = []
        coin = self.rl_coin
        puzzle_hash = coin.puzzle_hash

        pubkey, secretkey = self.get_keys(puzzle_hash)
        puzzle = self.rl_puzzle_for_pk(pubkey.serialize(), self.limit, self.interval)
        solution = self.solution_for_rl(coin.parent_coin_info, puzzle_hash, coin.amount, to_puzzlehash, amount)

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def rl_generate_signed_transaction(self, to_puzzle_hash, amount):

        if amount > self.rl_coin.amount:
            return None
        transaction = self.rl_generate_unsigned_transaction(to_puzzle_hash, amount)
        return self.rl_sign_transaction(transaction)

    # TODO track self.rl_coin blockage and calculate available spend amount
    def rl_balance(self):
        total_amount = self.rl_coin.amount
        available_amount = 0
        return total_amount, available_amount

    def rl_sign_transaction(self, spends: (Program, [CoinSolution])):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = self.get_keys(
                solution.coin.puzzle_hash)
            secretkey = BLSPrivateKey(secretkey)
            signature = secretkey.sign(
                ProgramHash(Program(solution.solution)))
            sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = CoinSolutionList(
            [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])) for
             (puzzle, coin_solution) in spends])
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    # This is for using the AC locked coin and aggregating it into wallet - must happen in same block as RL Mode 2
    def rl_generate_signed_aggregation_transaction(self):
        list_of_coinsolutions = []
        if self.aggregation_coins is False:  # empty sets evaluate to false in python
            return
        consolidating_coin = self.aggregation_coins.pop()

        pubkey, secretkey = self.get_keys(
            self.rl_coin.puzzle_hash)
        # Spend wallet coin
        puzzle =self.rl_puzzle_for_pk(pubkey.serialize(), self.limit, self.interval)
        solution = self.rl_make_solution_mode_2(self.rl_coin.puzzle_hash, consolidating_coin.parent_coin_info,
                                                consolidating_coin.puzzle_hash, consolidating_coin.amount, self.rl_coin.parent_coin_info, self.rl_coin.amount)

        signature = BLSPrivateKey(secretkey).sign(ProgramHash(solution))
        list_of_coinsolutions.append(CoinSolution(self.rl_coin, clvm.to_sexp_f([puzzle, solution])))

        # Spend consolidating coin
        puzzle = self.rl_make_aggregation_puzzle(self.rl_coin.puzzle_hash)
        solution = self.rl_make_aggregation_solution(consolidating_coin.name(
        ), self.rl_coin.parent_coin_info, self.rl_coin.amount)
        list_of_coinsolutions.append(CoinSolution(
            consolidating_coin, clvm.to_sexp_f([puzzle, solution])))
        # Spend lock
        puzstring = "(r (c (q 0x" + hexlify(consolidating_coin.name()
                                            ).decode('ascii') + ") (q ())))"
        puzzle = Program(binutils.assemble(puzstring))
        solution = Program(binutils.assemble("()"))
        list_of_coinsolutions.append(CoinSolution(Coin(self.rl_coin, ProgramHash(
            puzzle), 0), clvm.to_sexp_f([puzzle, solution])))

        aggsig = BLSSignature.aggregate([signature])
        solution_list = CoinSolutionList(list_of_coinsolutions)

        return SpendBundle(solution_list, aggsig)


    def get_new_puzzle(self):
        pubkey = self.get_next_public_key().serialize()
        puzzle = puzzle_for_pk(pubkey)
        return puzzle

    def get_new_puzzlehash(self):
        puzzle = self.get_new_puzzle()
        puzzlehash = ProgramHash(puzzle)
        return puzzlehash

    def rl_get_aggregation_puzzlehash(self, wallet_puzzle):
        return ProgramHash(self.rl_make_aggregation_puzzle(wallet_puzzle))
