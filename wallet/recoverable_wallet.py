import hashlib
import clvm
from wallet.wallet import Wallet
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.atoms import hexbytes
from chiasim.hashable import Program, ProgramHash, CoinSolution, SpendBundle, BLSSignature
from chiasim.hashable.CoinSolution import CoinSolutionList
from clvm_tools import binutils
from clvm import to_sexp_f, eval_f
from chiasim.validation.Conditions import (
    conditions_by_opcode, make_create_coin_condition, make_assert_my_coin_id_condition, make_assert_min_time_condition
)
from chiasim.validation.consensus import (
    conditions_for_solution, hash_key_pairs_for_conditions_dict, conditions_dict_for_solution
)
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from blspy import ExtendedPublicKey
from fractions import Fraction
from decimal import Decimal
import math
from wallet.chialisp import *


def hash_sha256(val):
    return hashlib.sha256(val).digest()


def make_solution(parent, puzzlehash, value, escrow_factor, primaries=[], min_time=0, me={}, recovery=False):
    conditions = []
    for primary in primaries:
        conditions.append(make_create_coin_condition(primary['puzzlehash'], primary['amount']))
    if min_time > 0:
        conditions.append(make_assert_min_time_condition(min_time))
    if me:
        conditions.append(make_assert_my_coin_id_condition(me['id']))
    conditions = [binutils.assemble("#q"), conditions]
    solution = [conditions, [], 1 if recovery else 0, parent, puzzlehash, value, math.floor(value * escrow_factor)]
    program = Program(to_sexp_f(solution))
    return program


def get_destination_puzzle_hash(solution):
    conditions_dict = conditions_dict_for_solution(solution)
    val = conditions_dict.get(ConditionOpcode.CREATE_COIN, [])
    assert(len(val) == 1)
    assert(len(val[0]) == 3)
    return val[0][1]


def aggsig_condition(key):
    op_aggsig = ConditionOpcode.AGG_SIG[0]
    return make_list(quote(op_aggsig),
                     quote(f'0x{hexbytes(key)}'),
                     sha256(wrap(args(0))))


class RecoverableWallet(Wallet):
    def __init__(self):
        super().__init__()
        # self.backup_public_key = self.extended_secret_key.public_child(self.next_address).get_public_key()
        self.backup_public_key = self.extended_secret_key.get_extended_public_key()
        self.backup_private_key = self.extended_secret_key.private_child(self.next_address).get_private_key()
        self.next_address += 1
        self.escrow_coins = set()

    def get_recovery_public_key(self):
        return self.backup_public_key

    def get_recovery_private_key(self):
        return self.backup_private_key


    def get_new_puzzle_with_params_and_root(self, root_pubkey, pubkey, escrow_factor):
        op_block_age_exceeds = ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS[0]
        op_create = ConditionOpcode.CREATE_COIN[0]
        op_consumed = ConditionOpcode.ASSERT_COIN_CONSUMED[0]
        solution = args(0)
        solution_args = args(1)
        secure_switch = args(2)
        parent = args(3)
        puzzle_hash = args(4)
        value = args(5)
        new_value = args(6)
        evaluate_solution = eval(solution, solution_args)
        standard_conditions = make_list(aggsig_condition(pubkey),
                                        terminator=evaluate_solution)
        duration = 3
        recovery_conditions = make_list(aggsig_condition(root_pubkey),
                                        make_list(quote(op_block_age_exceeds),
                                                  quote(duration)),
                                        terminator=evaluate_solution)
        escrow_puzzle = make_if(is_zero(secure_switch),
                                standard_conditions,
                                recovery_conditions)
        escrow_puzzlehash = f'0x' + str(hexbytes(ProgramHash(Program(binutils.assemble(escrow_puzzle)))))
        f = Fraction(escrow_factor)
        escrow_factor_numerator = quote(f.numerator)
        escrow_factor_denominator = quote(f.denominator)
        create_condition = make_if(equal(multiply(new_value, escrow_factor_denominator),
                                         multiply(value, escrow_factor_numerator)),
                                   make_list(quote(op_create), quote(escrow_puzzlehash), new_value),
                                   fail())
        coin_id = sha256(parent, puzzle_hash, uint64(value))
        consumed_condition = make_list(quote(op_consumed), coin_id)
        escrow_conditions = make_list(create_condition,
                                      consumed_condition)
        puzzle = make_if(is_zero(secure_switch),
                         standard_conditions,
                         escrow_conditions)
        program = Program(binutils.assemble(puzzle))
        return program

    def get_new_puzzle_with_params(self, pubkey, escrow_factor):
        return self.get_new_puzzle_with_params_and_root(self.backup_public_key.serialize(), pubkey, escrow_factor)

    def get_new_puzzle(self):
        pubkey = self.get_next_public_key().serialize()
        program = self.get_new_puzzle_with_params(pubkey, Decimal('1.1'))
        return program

    def get_new_puzzlehash(self):
        puzzle = self.get_new_puzzle()
        puzzlehash = ProgramHash(puzzle)
        return puzzlehash

    def can_generate_puzzle_hash(self, hash):
        return any(map(lambda child: hash == ProgramHash(self.get_new_puzzle_with_params(
            self.extended_secret_key.public_child(child).get_public_key().serialize(), Decimal('1.1'))),
                reversed(range(self.next_address))))

    def notify(self, additions, deletions):
        for coin in additions:
            if self.can_generate_puzzle_hash(coin.puzzle_hash):
                self.current_balance += coin.amount
                self.my_utxos.add(coin)
        for coin in deletions:
            if coin in self.my_utxos:
                self.my_utxos.remove(coin)
                self.current_balance -= coin.amount

        self.temp_utxos = self.my_utxos.copy()
        self.temp_balance = self.current_balance

    def can_generate_puzzle_hash_with_root_public_key(self, hash, root_public_key_serialized):
        root_public_key = ExtendedPublicKey.from_bytes(root_public_key_serialized)
        return any(map(lambda child: hash == ProgramHash(self.get_new_puzzle_with_params_and_root(
            root_public_key_serialized, root_public_key.public_child(child).get_public_key().serialize(), Decimal('1.1'))),
                reversed(range(20))))

    def find_pubkey_for_hash(self, hash, root_public_key_serialized, escrow_factor):
        root_public_key = ExtendedPublicKey.from_bytes(root_public_key_serialized)
        for child in reversed(range(20)):
            pubkey = root_public_key.public_child(child).get_public_key().serialize()
            puzzle = self.get_new_puzzle_with_params_and_root(root_public_key_serialized, pubkey, escrow_factor)
            puzzlehash = ProgramHash(puzzle)
            if hash == puzzlehash:
                return pubkey


    def get_keys(self, hash):
        for child in range(self.next_address):
            pubkey = self.extended_secret_key.public_child(child).get_public_key()
            if hash == ProgramHash(self.get_new_puzzle_with_params(pubkey.serialize(), Decimal('1.1'))):
                return pubkey, self.extended_secret_key.private_child(child).get_private_key()

    def generate_unsigned_transaction(self, amount, newpuzzlehash):
        escrow_factor = Decimal('1.1')
        utxos = self.select_coins(amount)
        spends = []
        output_id = None
        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount
        for coin in utxos:
            puzzle_hash = coin.puzzle_hash

            pubkey, secretkey = self.get_keys(puzzle_hash)
            puzzle = self.get_new_puzzle_with_params(pubkey.serialize(), escrow_factor)
            if output_id == None:
                primaries = [{'puzzlehash': newpuzzlehash, 'amount': amount}]
                if change > 0:
                    changepuzzlehash = self.get_new_puzzlehash()
                    primaries.append({'puzzlehash': changepuzzlehash, 'amount': change})
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor, primaries=primaries)
                output_id = hash_sha256(coin.name() + newpuzzlehash)
            else:
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor)
            spends.append((puzzle, CoinSolution(coin, solution)))
        return spends


    def generate_unsigned_transaction_without_recipient(self, amount):
        escrow_factor = Decimal('1.1')
        utxos = self.select_coins(amount)
        spends = []
        output_id = None
        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount
        for coin in utxos:
            puzzle_hash = coin.puzzle_hash

            pubkey, secretkey = self.get_keys(puzzle_hash)
            puzzle = self.get_new_puzzle_with_params(pubkey.serialize(), escrow_factor)
            if output_id == None:
                primaries = []
                if change > 0:
                    changepuzzlehash = self.get_new_puzzlehash()
                    primaries.append({'puzzlehash': changepuzzlehash, 'amount': change})
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor, primaries=primaries)
                output_id = True
            else:
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor)
            spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def generate_recovery_transaction(self, coins, pubkey):
        escrow_factor = Decimal('1.1')
        spends = []
        output_id = None
        amount = sum([coin.amount for coin in coins])
        newpuzzlehash = self.get_new_puzzlehash()
        for coin in coins:
            puzzle_hash = coin.puzzle_hash
            puzzle = self.get_escrow_puzzle_with_params(pubkey.serialize(), escrow_factor)
            if output_id == None:
                primaries = [{'puzzlehash': newpuzzlehash, 'amount': amount}]
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor, primaries=primaries)
                output_id = hash_sha256(coin.name() + newpuzzlehash)
            else:
                solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor)
            spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def generate_recovery_to_escrow_transaction(self, coin, root_public_key, pubkey, escrow_factor):
        solution = make_solution(coin.parent_coin_info, coin.puzzle_hash, coin.amount, escrow_factor, recovery=True)
        puzzle = self.get_new_puzzle_with_params_and_root(root_public_key, pubkey, escrow_factor)
        print("Puzzle   ", binutils.disassemble(puzzle))
        print("Solution ", binutils.disassemble(solution))

        sexp = clvm.to_sexp_f([puzzle, solution])
        destination_puzzle_hash = get_destination_puzzle_hash(sexp)
        staked_amount = math.ceil(coin.amount * (escrow_factor - 1))
        spends = self.generate_unsigned_transaction_without_recipient(staked_amount)
        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends, destination_puzzle_hash, coin.amount + staked_amount

    def generate_signed_recovery_transaction(self, coin, root_public_key, pubkey, escrow_factor):
        transaction, destination_puzzlehash, amount = self.generate_recovery_to_escrow_transaction(coin, root_public_key, pubkey, escrow_factor)
        return self.sign_transaction(transaction), destination_puzzlehash

    def sign_transaction(self, spends: (Program, CoinSolution)):
        sigs = []
        for puzzle, solution in spends:
            val = self.get_keys(solution.coin.puzzle_hash)
            if val is None:
                continue
            pubkey, secretkey = val
            secretkey = BLSPrivateKey(secretkey)
            code_ = [puzzle, solution.solution]
            sexp = clvm.to_sexp_f(code_)
            print(f'getting conditions for:\ncoin: {solution.coin}\npuzzle: {binutils.disassemble(puzzle)}\nsolution: {binutils.disassemble(solution.solution)}\n')
            conditions_dict = conditions_by_opcode(conditions_for_solution(sexp))
            for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
                signature = secretkey.sign(_.message_hash)
                sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = CoinSolutionList(
            [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])) for
             (puzzle, coin_solution) in spends])
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def generate_signed_transaction(self, amount, newpuzzlehash):
        transaction = self.generate_unsigned_transaction(amount, newpuzzlehash)
        if transaction is None:
            return None
        return self.sign_transaction(transaction)
