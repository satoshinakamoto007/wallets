import hashlib
import clvm
from standard_wallet.wallet import Wallet
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.hashable import Program, ProgramHash
from clvm_tools import binutils
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from chiasim.hashable import CoinSolution, SpendBundle, BLSSignature
from chiasim.hashable.CoinSolution import CoinSolutionList


class CCWallet(Wallet):

    def __init__(self):
        super().__init__()
        self.my_cores = []  # core is stored as a string
        self.my_coloured_coins = dict()  # {coin: (innerpuzhash, core)}
        return

    def notify(self, additions, deletions):
        self.cc_notify(additions)
        super().notify(additions, deletions)

    def cc_notify(self, additions):
        for coin in additions:
            for i in reversed(range(self.next_address)):
                innerpuz = puzzle_for_pk(self.extended_secret_key.public_child(i).get_public_key().serialize())
                for core in self.my_cores:
                    if ProgramHash(self.cc_make_puzzle(ProgramHash(innerpuz), core)) == coin.puzzle_hash:
                        self.my_coloured_coins[coin] = (innerpuz, core)
        return

    def cc_can_generate(self, finalpuzhash):
        for i in reversed(range(self.next_address)):
            innerpuzhash = ProgramHash(puzzle_for_pk(self.extended_secret_key.public_child(i).get_public_key().serialize()))
            for core in self.my_cores:
                if ProgramHash(self.cc_make_puzzle(innerpuzhash, core)) == finalpuzhash:
                    return True
        return False

    def cc_add_core(self, core):
        self.my_cores.append(core)
        return

    # This is for generating a new set of coloured coins - this may be moved out of this wallet
    def cc_generate_spend_for_genesis_coins(self, amount, innerpuzhash, genesisCoin=None):
        if genesisCoin is None:
            my_utxos_copy = self.temp_utxos.copy()
            genesisCoin = my_utxos_copy.pop()
            while genesisCoin.amount < amount and len(my_utxos_copy) > 0:
                genesisCoin = my_utxos_copy.pop()
        core = self.cc_make_core(genesisCoin.name())
        self.cc_add_core(core)
        newpuzzle = self.cc_make_puzzle(innerpuzhash, core)
        newpuzzlehash = ProgramHash(newpuzzle)
        spend_bundle = self.generate_signed_transaction(amount, newpuzzlehash)
        return spend_bundle

    # we use it to merge the outputs of two programs that create lists
    def merge_two_lists(list1=None, list2=None):
        if (list1 is None) or (list2 is None):
            return None
        ret = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i ((c (i (f (r (a))) (q (q ())) (q (q 1))) (a))) (q (f (c (f (r (r (a)))) (q ())))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (q ())))))))) (a)))) (c {list1} (c {list2} (q ()))))))"
        return ret

    # This is for spending an existing coloured coin
    def cc_make_puzzle(self, innerpuzhash, core):
        puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
        print(f"DEBUG Puzstring: {puzstring}")
        return Program(binutils.assemble(puzstring))

    # TODO: Ask Bram about this - core is "the colour"
    # Actually a colour specific filter program that checks parents - what format?
    def cc_make_core(self, originID):
        # Confirmed working.
        create_outputs = f"((c (f (r (r (r (a))))) (f (r (r (r (r (a))))))))"
        sum_outputs = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 0x{ConditionOpcode.CREATE_COIN.hex()})) (q (+ (f (r (r (f (f (r (a))))))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (+ (q ()) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ())))))))) (a)))) (q (q ()))) (a)))) (c {create_outputs} (q ())))))"


        # Solution when wrapped in recursive wrapper looks like - (("source") ((51 0xdeadbeef 200)) (q "core") ())
        # fullpuz_for_parent_innerpuz = f"(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"
        # new_createcondition_for_innerpuz = f"(c (q 51) (c (sha256tree {fullpuz_for_parent_innerpuz}) (c (f (r (r (f (f (r (a))))))) (q ()))))"

        # new_createcoin = f"((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c {new_createcondition_for_innerpuz} (f (r (r (r (a)))))) (q ())))))))"

        # python_loop = f"""
        #((c (i (f (r (a)))
        #   (q ((c (i (= (f (f (f (r (a))))) (q 51))
    #         (q {new_createcoin})
    #         (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (f (f (r (a)))) (f (r (r (r (a)))))) (q ()))))))))
    #            ) (a)))
    #        )
    #        (q (f (r (r (r (a))))))
    #    ) (a)))"""

        # below is confirmed working raw chialisp - to be converted to nice python later
        replace_generated_createcoins = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 0x{ConditionOpcode.CREATE_COIN.hex()})) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (c (q 0x{ConditionOpcode.CREATE_COIN.hex()}) (c (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (c (f (r (r (f (f (r (a))))))) (q ())))) (f (r (r (r (a)))))) (q ())))))))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (f (f (r (a)))) (f (r (r (r (a)))))) (q ())))))))) ) (a))) ) (q (f (r (r (r (a)))))) ) (a)))) (c {create_outputs} (c (f (a)) (c (q ()) (q ())))))))"



        add_core_to_parent_innerpuzhash = "(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (a))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"
        add_core_to_my_innerpuz_reveal = "(c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256tree (f (r (r (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"

        assert_my_parent_is_origin = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (f (r (a))) (sha256tree {add_core_to_my_innerpuz_reveal}) {sum_outputs}) (q ())))"

        assert_my_parent_follows_core_logic = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree {add_core_to_parent_innerpuzhash}) (f (r (r (f (r (a))))))) (sha256tree {add_core_to_my_innerpuz_reveal}) {sum_outputs}) (q ())))"

        heritage_check = f"((c (i (l (f (r (a)))) (q {assert_my_parent_follows_core_logic}) (q ((c (i (= (q 0x{originID}) (f (r (a)))) (q {assert_my_parent_is_origin}) (q (x))) (a)))) ) (a)))"

        core = f"(c {heritage_check} {replace_generated_createcoins})"
        breakpoint()
        return core

    # This is for spending a recieved coloured coin
    def cc_make_solution(self, core, parent_info, amount, innerpuzreveal, innersol):
        parent_str = ""
        # parent_info is a triplet or the originID
        # genesis coin isn't coloured, child of genesis uses originID, all subsequent children use triplets
        if isinstance(parent_info, list):
            #  (parent primary input, parent inner puzzle hash, parent amount)
            parent_str = f"(0x{parent_info[0]} 0x{parent_info[1]} {parent_info[2]})"
        else:
            parent_str = f"0x{parent_info.hex()}"
        sol = f"({core} {parent_str} {amount} {innerpuzreveal} {innersol})"
        print(f"DEBUG solstring: {sol}")
        return Program(binutils.assemble(sol))

    # This is for spending a recieved coloured coin
    def cc_generate_signed_transaction(self, coin, parent_info, amount, innersol, sigs=[]):
        innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])

        core = self.my_coloured_coins[coin][1]
        solution = self.cc_make_solution(core, parent_info, amount, innerpuz, binutils.disassemble(innersol))
        solution_list = CoinSolutionList([CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution]))])
        breakpoint()
        aggsig = BLSSignature.aggregate(sigs)
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
