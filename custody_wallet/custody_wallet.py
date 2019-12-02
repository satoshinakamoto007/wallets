from chiasim.atoms import hexbytes
from standard_wallet.wallet import *
import clvm
from chiasim.hashable import Program, ProgramHash, CoinSolution, SpendBundle, BLSSignature
from binascii import hexlify
from chiasim.hashable.Coin import Coin
from chiasim.hashable.CoinSolution import CoinSolutionList
from clvm_tools import binutils
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
import math

# CPWallet is subclass of Wallet
class CPWallet(Wallet):
    def __init__(self):
        self.pubkey_orig = None
        self.all_cp_additions = {}
        self.all_cp_deletions = {}
        self.pubkey_permission = None
        self.pubkey_approval = None
        self.lock_index = 0
        self.tip_index = 0
        self.cp_balance = 0
        self.cp_coin = None
        super().__init__()
        return

    def notify(self, additions, deletions, index):
        super().notify(additions, deletions)
        self.tip_index = index
        self.cp_notify(additions, deletions, index)

    def cp_notify(self, additions, deletions, index):
        for coin in additions:
            if coin.name() in self.all_cp_additions:
                continue
            self.all_cp_additions[coin.name()] = coin
            if self.can_generate_cp_puzzle_hash(coin.puzzle_hash):
                self.cp_balance += coin.amount
                self.cp_coin = coin
        for coin in deletions:
            if coin.name() in self.all_cp_deletions:
                continue
            self.all_cp_deletions[coin.name()] = coin
            if self.can_generate_cp_puzzle_hash(coin.puzzle_hash):
                self.cp_balance -= coin.amount

    def can_generate_cp_puzzle_hash(self, hash):
        if self.pubkey_permission is None:
            return None
        return any(map(lambda child: hash == ProgramHash(self.cp_puzzle(
            hexbytes(self.extended_secret_key.public_child(child).get_public_key().serialize()), self.pubkey_permission, self.lock_index)),
                       reversed(range(self.next_address))))

    def merge_two_lists(self, list1=None, list2=None):
        if (list1 is None) or (list2 is None):
            return None
        ret = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i ((c (i (f (r (a))) (q (q ())) (q (q 1))) (a))) (q (f (c (f (r (r (a)))) (q ())))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (q ())))))))) (a)))) (c {list1} (c {list2} (q ()))))))"
        return ret

    def cp_puzzle(self, pubkey_my, pubkey_permission, lock_index):
        opcode_aggsig = hexlify(ConditionOpcode.AGG_SIG).decode('ascii')
        opcode_block_index = hexlify(ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS).decode('ascii')

        INDEX_EXCEEDS = f"(c (q 0x{opcode_block_index}) (c (q {lock_index}) (q ())))"
        AGGSIG_ME = f"(c (q 0x{opcode_aggsig}) (c (q 0x{pubkey_my}) (c (sha256 (wrap (a))) (q ()))))"
        AGGSIG_PERMISSION = f"(c (q 0x{opcode_aggsig}) (c (q 0x{pubkey_permission}) (c (sha256 (wrap (a))) (q ()))))"
        SOLO_PUZZLE_CONDITIONS = f"(c {INDEX_EXCEEDS} (c {AGGSIG_ME} (q ())))"
        SOLUTION_OUTPUTS = f"(f (r (a)))"
        SOLO_PUZZLE = self.merge_two_lists(SOLO_PUZZLE_CONDITIONS, SOLUTION_OUTPUTS)
        PERMISSION_PUZZLE_CONDITIONS = f"(c {AGGSIG_PERMISSION} (c {AGGSIG_ME} (q ())))"
        PERMISSION_PUZZLE = self.merge_two_lists(PERMISSION_PUZZLE_CONDITIONS, SOLUTION_OUTPUTS)
        WHOLE_PUZZLE = f"(i (= (f (a)) (q 1)) {SOLO_PUZZLE} {PERMISSION_PUZZLE})"
        return Program(binutils.assemble(WHOLE_PUZZLE))

    def solution_for_cp_solo(self, puzzlehash_amount_list=[]):
        opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode('ascii')
        sol = "(1 ("
        for puzhash, amount in puzzlehash_amount_list:
            sol += f"(0x{opcode_create} 0x{hexlify(puzhash).decode('ascii')} {amount})"
        sol += f"))"
        return Program(binutils.assemble(sol))

    def solution_for_cp_permission(self, puzzlehash_amount_list=[]):
        opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode('ascii')
        sol = "(2 ("
        for puzhash, amount in puzzlehash_amount_list:
            sol += f"(0x{opcode_create} 0x{hexlify(puzhash).decode('ascii')} {amount})"
        sol += f"))"
        return Program(binutils.assemble(sol))

    def get_keys(self, hash):
        s = super().get_keys(hash)
        if s is not None:
            return s
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hash == ProgramHash(
                    self.cp_puzzle(hexbytes(pubkey.serialize()), self.pubkey_permission, self.lock_index)):
                return pubkey, self.extended_secret_key.private_child(child).get_private_key()

    def get_keys_pk(self, approval_pubkey):
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hexbytes(pubkey.serialize()) == approval_pubkey:
                return pubkey, self.extended_secret_key.private_child(child).get_private_key()

    def cp_generate_unsigned_transaction(self, new_puzzle_hash, amount, mode):
        outputs = []
        output = new_puzzle_hash, amount
        outputs.append(output)
        change = self.cp_coin.amount - amount
        if change > 0:
            change_output = self.cp_coin.puzzle_hash, change
            outputs.append(change_output)
        spends = []
        puzzle_hash = self.cp_coin.puzzle_hash
        pubkey, secretkey = self.get_keys(puzzle_hash)
        puzzle = self.cp_puzzle(hexbytes(pubkey.serialize()), self.pubkey_permission, self.lock_index)
        if mode == 1:
            solution = self.solution_for_cp_solo(outputs)
        else:
            solution = self.solution_for_cp_permission(outputs)
        spends.append((puzzle, CoinSolution(self.cp_coin, solution)))
        return spends

    '''
    Mode == 1 is when only our signature is required (lock time has passed)
    Mode == 2 is when both signatures are required
    '''
    def cp_generate_signed_transaction(self, puzzlehash, amount):
        if amount > self.cp_balance:
            return None
        transaction = self.cp_generate_unsigned_transaction(puzzlehash, amount, 1)
        return self.cp_sign_transaction(transaction)

    def cp_generate_signed_transaction_with_approval(self, puzzlehash, amount, approval):
        if amount > self.cp_balance:
            return None
        transaction = self.cp_generate_unsigned_transaction(puzzlehash, amount, 2)
        return self.cp_sign_transaction(transaction, approval)

    def cp_approval_signature_for_transaction(self, solution):
        pubkey, secretkey = self.get_keys_pk(self.pubkey_approval)
        secretkey = BLSPrivateKey(secretkey)
        signature = secretkey.sign(ProgramHash(Program(solution)))
        return signature

    def cp_sign_transaction(self, spends: (Program, [CoinSolution]), approval=None):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = self.get_keys(
                solution.coin.puzzle_hash)
            secretkey = BLSPrivateKey(secretkey)
            signature = secretkey.sign(
                ProgramHash(Program(solution.solution)))
            sigs.append(signature)
        if approval is not None:
            app = BLSSignature(approval)
            sigs.append(app)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = CoinSolutionList(
            [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])) for
             (puzzle, coin_solution) in spends])
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle


"""
Copyright 2018 Chia Network Inc
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""