import clvm
import string
from standard_wallet.wallet import Wallet
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.hashable import Program, ProgramHash, Coin
from clvm_tools import binutils
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from chiasim.hashable import CoinSolution, SpendBundle, BLSSignature
from chiasim.hashable.CoinSolution import CoinSolutionList
from chiasim.validation.Conditions import conditions_by_opcode
from chiasim.validation.consensus import (
    conditions_for_solution, hash_key_pairs_for_conditions_dict
)


class CCWallet(Wallet):
    def __init__(self):
        super().__init__()
        self.my_cores = set()  # core is stored as a string
        self.my_coloured_coins = dict()  # {coin: (innerpuzzle as Program, core as string)}
        self.eve_coloured_coins = dict()
        self.parent_info = dict()
        return

    def notify(self, additions, deletions, body):
        self.cc_notify(additions, deletions, body)
        super().notify(additions, deletions)

    def cc_notify(self, additions, deletions, body):
        search_for_parent = False
        for coin in additions:
            for i in reversed(range(self.next_address)):
                innerpuz = puzzle_for_pk(bytes(self.extended_secret_key.public_child(i)))
                for core in self.my_cores:
                    if ProgramHash(self.cc_make_puzzle(ProgramHash(innerpuz), core)) == coin.puzzle_hash:
                        self.my_coloured_coins[coin] = (innerpuz, core)
                        search_for_parent = True
        for coin in deletions:
            if coin in self.my_coloured_coins:
                self.my_coloured_coins.pop(coin)
            if search_for_parent:
                for cc in self.my_coloured_coins:
                    if coin.name() == cc.parent_coin_info:
                        # inspect body object for solution reveal
                        result = clvm.run_program(body.solution_program, binutils.assemble("()"))[1]
                        while result != b'':
                            tuple = result.first()
                            if tuple.first() == coin.name():
                                puzzle = tuple.rest().first().first()
                                if self.check_is_cc_puzzle(puzzle):
                                    innerpuzhash = binutils.disassemble(puzzle)[9:75]
                                    self.parent_info[coin.name()] = (coin.parent_coin_info, innerpuzhash, coin.amount)
                                else:  # must be a genesis parent
                                    self.parent_info[coin.name()] = coin.name()

                            result = result.rest()
        return

    def check_is_cc_puzzle(self, puzzle):
        puzstring = binutils.disassemble(puzzle)
        if len(puzstring) < 5300:
            return False
        innerpuz = puzstring[11:75]
        if all(c in string.hexdigits for c in innerpuz) is not True:
            return False
        genesisCoin = self.get_genesis_from_puzzle(puzstring)
        if all(c in string.hexdigits for c in genesisCoin) is not True:
            return False
        if self.cc_make_puzzle(innerpuz, self.cc_make_core(genesisCoin)) == puzzle:
            return True
        else:
            return False

    def get_genesis_from_puzzle(self, core):
        return core[-596:].split(')')[0]

    def get_genesis_from_core(self, core):
        return core[-589:].split(')')[0]

    def cc_can_generate(self, finalpuzhash):
        for i in reversed(range(self.next_address)):
            innerpuzhash = ProgramHash(puzzle_for_pk(bytes(self.extended_secret_key.public_child(i))))
            for core in self.my_cores:
                if ProgramHash(self.cc_make_puzzle(innerpuzhash, core)) == finalpuzhash:
                    return True
        return False

    def cc_add_core(self, core):
        self.my_cores.add(core)
        return

    # This is for generating a new set of coloured coins
    def cc_generate_spend_for_genesis_coins(self, amounts, genesisCoin=None):
        total_amount = sum(amounts)
        if total_amount > self.temp_balance:
            return None
        secondary_coins = []
        genesisCoin = self.temp_utxos.pop()
        while genesisCoin.amount + sum([x.amount for x in secondary_coins]) < total_amount:
            secondary_coins.append(self.temp_utxos.pop())
        core = self.cc_make_core(genesisCoin.name())
        self.cc_add_core(core)
        spends = []
        change = genesisCoin.amount + sum([x.amount for x in secondary_coins])
        change = change - total_amount

        # Aped from wallet.generate_unsigned_transaction()
        pubkey, secretkey = self.get_keys(genesisCoin.puzzle_hash)

        puzzle = self.puzzle_for_pk(bytes(pubkey))
        primaries = []
        evespendslist = []
        for amount in amounts:
            innerpuz = self.get_new_puzzle()
            innerpuzhash = ProgramHash(innerpuz)
            newpuzzle = self.cc_make_puzzle(innerpuzhash, core)
            newpuzzlehash = ProgramHash(newpuzzle)
            primaries.append({'puzzlehash': newpuzzlehash, 'amount': amount})
            evespendslist.append((Coin(genesisCoin, newpuzzlehash, amount), genesisCoin.name(), amount, binutils.assemble("((q ()) ())")))
            self.eve_coloured_coins[Coin(genesisCoin, newpuzzlehash, amount)] = (innerpuz, core)
        if change > 0:
            changepuzzlehash = self.get_new_puzzlehash()
            primaries.append(
                {'puzzlehash': changepuzzlehash, 'amount': change})
            # add change coin into temp_utxo set
            self.temp_utxos.add(Coin(genesisCoin, changepuzzlehash, change))
        solution = self.make_solution(primaries=primaries)
        spends.append((puzzle, CoinSolution(genesisCoin, solution)))
        solution = self.make_solution(consumed=[genesisCoin.name()])

        for coin in secondary_coins:
            pubkey, secretkey = self.get_keys(coin.puzzle_hash)
            puzzle = self.puzzle_for_pk(bytes(pubkey))
            spends.append((puzzle, CoinSolution(coin, solution)))

        self.temp_balance -= total_amount
        spend_bundle = self.sign_transaction(spends)
        spend_bundle = spend_bundle.aggregate([spend_bundle, self.cc_generate_eve_spend(evespendslist)])
        return spend_bundle

    def cc_create_zero_val_for_core(self, core):
        if self.temp_utxos == set():
            return None
        innerpuz = self.get_new_puzzle()
        newpuzzle = self.cc_make_puzzle(ProgramHash(innerpuz), core)
        coin = self.temp_utxos.pop()
        primaries = [{'puzzlehash': ProgramHash(newpuzzle), 'amount': 0}]
        changepuzzlehash = self.get_new_puzzlehash()
        primaries.append(
        {'puzzlehash': changepuzzlehash, 'amount': coin.amount})
        # add change coin into temp_utxo set
        self.temp_utxos.add(Coin(coin, changepuzzlehash, coin.amount))
        solution = self.make_solution(primaries=primaries)
        pubkey, secretkey = self.get_keys(coin.puzzle_hash)
        puzzle = puzzle_for_pk(pubkey)
        spend_bundle = self.sign_transaction([(puzzle, CoinSolution(coin, solution))])

        # Eve spend
        coin = Coin(coin, ProgramHash(newpuzzle), 0)
        solution = self.cc_make_solution(core, coin.parent_coin_info, coin.amount, binutils.disassemble(innerpuz), "((q ()) ())", None, None)
        eve_spend = SpendBundle([CoinSolution(coin, clvm.to_sexp_f([newpuzzle, solution]))], BLSSignature.aggregate([]))
        spend_bundle = spend_bundle.aggregate([spend_bundle, eve_spend])
        self.parent_info[coin.name()] = (coin.parent_coin_info, coin.puzzle_hash, coin.amount)
        self.eve_coloured_coins[Coin(coin, coin.puzzle_hash, 0)] = (innerpuz, core)
        return spend_bundle

    # we use it to merge the outputs of two programs that create lists
    def merge_two_lists(self, list1=None, list2=None):
        if (list1 is None) or (list2 is None):
            return None
        ret = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i ((c (i (f (r (a))) (q (q ())) (q (q 1))) (a))) (q (f (c (f (r (r (a)))) (q ())))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (q ())))))))) (a)))) (c {list1} (c {list2} (q ()))))))"
        return ret

    # This is for spending an existing coloured coin
    def cc_make_puzzle(self, innerpuzhash, core):
        puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
        #print(f"DEBUG Puzstring: {puzstring}")
        return Program(binutils.assemble(puzstring))

    # Typically called only once per colour then passed around or inferred from a coin
    def cc_make_core(self, originID):
        create_outputs = f"((c (f (r (r (r (a))))) (f (r (r (r (r (a))))))))"
        sum_outputs = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 0x{ConditionOpcode.CREATE_COIN.hex()})) (q (+ (f (r (r (f (f (r (a))))))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (+ (q ()) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ())))))))) (a)))) (q (q ()))) (a)))) (c {create_outputs} (q ())))))"

        # python_loop = f"""
        #((c (i (f (r (a)))
        #   (q ((c (i (= (f (f (f (r (a))))) (q 51))
    #         (q {new_createcoin})
    #         (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (f (f (r (a)))) (f (r (r (r (a)))))) (q ()))))))))
    #            ) (a)))
    #        )
    #        (q (f (r (r (r (a))))))
    #    ) (a)))"""

        # below is confirmed working raw chialisp - to be converted to nice python above later
        replace_generated_createcoins = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 0x{ConditionOpcode.CREATE_COIN.hex()})) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (c (q 0x{ConditionOpcode.CREATE_COIN.hex()}) (c (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (c (f (r (r (f (f (r (a))))))) (q ())))) (f (r (r (r (a)))))) (q ())))))))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (c (f (f (r (a)))) (f (r (r (r (a)))))) (q ())))))))) ) (a))) ) (q (f (r (r (r (a)))))) ) (a)))) (c {create_outputs} (c (f (a)) (c (q ()) (q ())))))))"

        add_core_to_parent_innerpuzhash = "(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (a))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"
        add_core_to_my_innerpuz_reveal = "(c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256tree (f (r (r (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"

        # Because we add core to our innerpuz reveal as part of our ASSERT_MY_ID we also check that our innerpuzreveal is correct
        assert_my_parent_is_origin = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (f (r (a))) (sha256tree {add_core_to_my_innerpuz_reveal}) (f (r (r (a))))) (q ())))"

        assert_my_parent_follows_core_logic = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree {add_core_to_parent_innerpuzhash}) (f (r (r (f (r (a))))))) (sha256tree {add_core_to_my_innerpuz_reveal}) (f (r (r (a))))) (q ())))"

        # heritage_check = f"((c (i (l (f (r (a)))) (q {assert_my_parent_follows_core_logic}) (q ((c (i (= (q 0x{originID}) (f (r (a)))) (q {assert_my_parent_is_origin}) (q (x))) (a)))) ) (a)))"

        add_core_to_auditor_innerpuzhash = f"(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (r (r (r (r (a))))))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"
        create_a_puz_for_cn = f"(c (q #r) (c (c (q #c) (c (c (q #q) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree {add_core_to_parent_innerpuzhash}) (f (r (r (f (r (a))))))) (sha256tree {add_core_to_my_innerpuz_reveal}) (f (r (r (a))))) (q ()))) (q ((q ()))))) (q ())))"

        consume_a = f"(c (q 52) (c (sha256 (sha256 (f (f (r (r (r (r (r (a)))))))) (sha256tree {add_core_to_auditor_innerpuzhash}) (f (r (r (f (r (r (r (r (r (a))))))))))) (sha256tree {create_a_puz_for_cn}) (q 0)) (q ())))"

        create_e_puz = f"(c (q #r) (c (c (q #r) (c (c (q #c) (c (c (q #q) (c (sha256 (f (f (r (r (r (r (r (a)))))))) (sha256tree {add_core_to_auditor_innerpuzhash}) (f (r (r (f (r (r (r (r (r (a))))))))))) (q ()))) (c (c (q #c) (c (c (q #q) (c {sum_outputs} (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ())))"
        create_e = f"(c (q 51) (c (sha256tree {create_e_puz}) (c (q 0) (q ()))))"

        consume_es_generate_as = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c (c (c (q 51) (c (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256 (f (f (f (r (a))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (f (r (r (f (f (r (a)))))))) (q ()))) (q ((q ()))))) (q ())))) (q (0)))) (c (c (q 52) (c (sha256 (sha256 (f (f (f (r (a))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (f (r (r (f (f (r (a)))))))) (sha256tree (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (f (f (r (a)))))))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ())))) (q 0)) (q ()))) (f (r (r (r (r (a)))))))) (q ()))))))))) (q (f (r (r (r (r (a)))))))) (a))))(c (f (r (r (r (r (r (r (a)))))))) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (a))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (f (r (r (f (r (a))))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256tree (f (r (r (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (f (r (r (a))))) (c (f (a)) (q (()))))))))"

        compare_sums = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (a))))) (c (+ (f (r (r (r (f (f (r (a)))))))) (f (r (r (r (a)))))) (q ())))))))) (q (= (f (r (r (a)))) (f (r (r (r (a)))))))) (a)))) (c (f (r (r (r (r (r (r (a)))))))) (q (() ()))))))"

        auditor_code_path = f"((c (i (f (r (r (r (r (r (r (a)))))))) (q ((c (i {compare_sums} (q {consume_es_generate_as}) (q (x))) (a)))) (q (q ()))) (a)))"

        normal_case = f"(c {consume_a} (c {create_e} (c {assert_my_parent_follows_core_logic} {self.merge_two_lists(replace_generated_createcoins, auditor_code_path)})))"

        create_child_with_my_puzzle = f"(c (q 51) (c (sha256tree {add_core_to_my_innerpuz_reveal}) (c (f (r (r (a)))) (q ()))))"
        #eve_case = f"((c (i (= (q 0x{originID}) (f (r (a)))) (q (c {assert_my_parent_is_origin} (c {create_child_with_my_puzzle} (q ())))) (q (x))) (a)))"
        assert_my_value_zero = f"(c (q 53) (c (sha256 (f (r (a))) (sha256tree {add_core_to_my_innerpuz_reveal}) (q 0)) (q ())))"
        eve_case = f"(c {create_child_with_my_puzzle} ((c (i (= (q 0x{originID}) (f (r (a)))) (q (c {assert_my_parent_is_origin} (q ()))) (q (c {assert_my_value_zero} (q ())))) (a))))"
        core = f"((c (i (l (f (r (a)))) (q {normal_case}) (q {eve_case}) ) (a)))"
        #breakpoint()
        return core

    # This is for spending a recieved coloured coin
    def cc_make_solution(self, core, parent_info, amount, innerpuzreveal, innersol, auditor, auditees=None):
        parent_str = ""
        # parent_info is a triplet or the originID
        # genesis coin isn't coloured, child of genesis uses originID, all subsequent children use triplets
        # auditor is (primary_input, innerpuzzlehash, amount)
        if isinstance(parent_info, tuple):
            #  (parent primary input, parent inner puzzle hash, parent amount)
            if parent_info[1][0:2] == "0x":
                parent_str = f"(0x{parent_info[0]} {parent_info[1]} {parent_info[2]})"
            else:
                parent_str = f"(0x{parent_info[0]} 0x{parent_info[1]} {parent_info[2]})"
        else:
            parent_str = f"0x{parent_info.hex()}"

        auditor_formatted = "()"
        if auditor is not None:
            auditor_formatted = f"(0x{auditor[0]} 0x{auditor[1]} {auditor[2]})"

        aggees = "("
        if auditees is not None:
            for auditee in auditees:
                # spendslist is [] of (coin, parent_info, outputamount, innersol, innerpuzhash=None)
                # aggees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                if auditee[0] in self.my_coloured_coins:
                    aggees = aggees + f"(0x{auditee[0].parent_coin_info} 0x{ProgramHash(self.my_coloured_coins[auditee[0]][0])} {auditee[0].amount} {auditee[2]})"
                else:
                    aggees = aggees + f"(0x{auditee[0].parent_coin_info} 0x{auditee[4]} {auditee[0].amount} {auditee[2]})"

        aggees = aggees + ")"

        sol = f"({core} {parent_str} {amount} {innerpuzreveal} {innersol} {auditor_formatted} {aggees})"
        #print(f"DEBUG solstring: {sol}")
        return Program(binutils.assemble(sol))

    # A newly minted coloured coin has a special spend before it can act like normal
    def cc_generate_eve_spend(self, spendslist, sigs=[]):
        # spendslist is [] of (coin, parent_info, outputamount, innersol)
        auditor = spendslist[0][0]
        core = None
        if auditor in self.my_coloured_coins:
            innerpuz = binutils.disassemble(self.my_coloured_coins[auditor][0])
            core = self.my_coloured_coins[auditor][1]
        elif auditor in self.eve_coloured_coins:
                innerpuz = binutils.disassemble(self.eve_coloured_coins[auditor][0])
                core = self.eve_coloured_coins[auditor][1]
        list_of_solutions = []
        for spend in spendslist:
            coin = spend[0]
            innersol = spend[3]
            parent_info = spend[1]
            if coin in self.my_coloured_coins:
                innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])
                solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), None, None)
                list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution])))
            elif coin in self.eve_coloured_coins:
                    innerpuz = binutils.disassemble(self.eve_coloured_coins[coin][0])
                    solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), None, None)
                    list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.eve_coloured_coins[coin][0]), core), solution])))

        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def cc_generate_spends_for_coin_list(self, spendslist, sigs=[]):
        # spendslist is [] of (coin, parent_info, outputamount, innersol)
        auditor = spendslist[0][0]
        core = self.my_coloured_coins[auditor][1]
        auditor_info = (auditor.parent_coin_info, ProgramHash(self.my_coloured_coins[auditor][0]), auditor.amount)
        list_of_solutions = []

        # auditor special case
        spend = spendslist[0]
        coin = spend[0]
        innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])
        innersol = spend[3]
        parent_info = spend[1]
        solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), auditor_info, spendslist)
        list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution])))
        list_of_solutions.append(self.create_spend_for_ephemeral(coin, auditor, spend[2]))
        list_of_solutions.append(self.create_spend_for_auditor(auditor, coin))

        # loop through remaining aggregatees
        for spend in spendslist[1:]:
            coin = spend[0]
            innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])
            innersol = spend[3]
            parent_info = spend[1]
            solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), auditor_info, None)
            list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution])))
            list_of_solutions.append(self.create_spend_for_ephemeral(coin, auditor, spend[2]))
            list_of_solutions.append(self.create_spend_for_auditor(auditor, coin))

        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def cc_select_coins_for_colour(self, colour, amount):
        coins = []
        total = 0
        for x in list(self.my_coloured_coins.keys()):
            if self.get_genesis_from_core(self.my_coloured_coins[x][1]) == colour:
                coins.append(x)
                total += x.amount
            if total >= amount and coins != []:
                break
        if total < amount:
            return None
        return coins

    def create_spend_for_ephemeral(self, parent_of_e, auditor_coin, spend_amount):
        puzstring = f"(r (r (c (q 0x{auditor_coin.name()}) (c (q {spend_amount}) (q ())))))"
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_e, ProgramHash(puzzle), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        #breakpoint()
        return coinsol

    def create_spend_for_auditor(self, parent_of_a, auditee):
        puzstring = f"(r (c (q 0x{auditee.name()}) (q ())))"
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_a, ProgramHash(puzzle), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        #breakpoint()
        return coinsol

    # This runs an innerpuz for an innersol
    def get_sigs_for_innerpuz_with_innersol(self, innerpuz, innersol):
        sigs = []
        pubkey, secretkey = self.get_keys(ProgramHash(innerpuz))
        code_ = [innerpuz, innersol]
        sexp = clvm.to_sexp_f(code_)
        conditions_dict = conditions_by_opcode(
            conditions_for_solution(sexp))
        for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
            signature = secretkey.sign(_.message_hash)
            sigs.append(signature)
        return sigs

    def create_trade_offer(self, trade_list):
        # trade_list is [] of (relativeamount, core)
        spend_bundle = None
        for amountcore in trade_list:
            if amountcore[1] is None:
                new_spend_bundle = self.create_spend_bundle_relative_chia(amountcore[0])
                if new_spend_bundle is None:
                    return None
                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = spend_bundle.aggregate([spend_bundle, new_spend_bundle])
            else:
                new_spend_bundle = self.create_spend_bundle_relative_core(amountcore[0], amountcore[1])
                if new_spend_bundle is None:
                    return None
                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = spend_bundle.aggregate([spend_bundle, new_spend_bundle])
        return spend_bundle

    def create_spend_bundle_relative_core(self, cc_amount, core):
        # Coloured Coin processing
        spend_bundle = None
        if cc_amount < 0:
            cc_spends = self.cc_select_coins_for_colour(self.get_genesis_from_core(core), abs(cc_amount))
        else:
            cc_spends = self.cc_select_coins_for_colour(self.get_genesis_from_core(core), 0)
        if cc_spends is None:
            return None

        spend_value = sum([coin.amount for coin in cc_spends])
        cc_amount = spend_value + cc_amount
        list_of_solutions = []
        output_created = None
        sigs = []
        for coin in cc_spends:
            if output_created is None:
                newinnerpuzhash = self.get_new_puzzlehash()
                innersol = self.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': cc_amount}])
                output_created = coin
            else:
                innersol = self.make_solution(consumed=[output_created.name()])
            if coin in self.my_coloured_coins:
                innerpuz = self.my_coloured_coins[coin][0]
            elif coin in self.eve_coloured_coins:
                innerpuz = self.eve_coloured_coins[coin][0]
            solution = self.cc_make_solution(core, self.parent_info[coin.parent_coin_info], coin.amount, binutils.disassemble(innerpuz), binutils.disassemble(innersol), None, None)
            list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(innerpuz), core), solution])))
            sigs = sigs + self.get_sigs_for_innerpuz_with_innersol(innerpuz, innersol)

        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        if spend_bundle is None:
            spend_bundle = SpendBundle(solution_list, aggsig)
        else:
            spend_bundle = spend_bundle.aggregate([spend_bundle, SpendBundle(solution_list, aggsig)])
        return spend_bundle

    def create_spend_bundle_relative_chia(self, chia_amount):
        list_of_solutions = []
        # standard coin CoinSolution generation
        utxos = self.select_coins(abs(chia_amount))
        if utxos is None:
            return None
        spend_value = sum([coin.amount for coin in utxos])
        chia_amount = spend_value + chia_amount
        output_created = None
        sigs = []
        for coin in utxos:
            pubkey, secretkey = self.get_keys(coin.puzzle_hash)
            puzzle = self.puzzle_for_pk(bytes(pubkey))
            if output_created is None:
                newpuzhash = self.get_new_puzzlehash()
                primaries = [{'puzzlehash': newpuzhash, 'amount': chia_amount}]
                self.temp_utxos.add(Coin(coin, newpuzhash, chia_amount))
                solution = self.make_solution(primaries=primaries)
                output_created = coin
            else:
                solution = self.make_solution(consumed=[output_created.name()])
            list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([puzzle, solution])))
            sigs = sigs + self.get_sigs_for_innerpuz_with_innersol(puzzle, solution)

        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def get_relative_amounts_for_trade_offer(self, trade_offer):
        cc_discrepancy = dict()
        for coinsol in trade_offer.coin_solutions:
            puzzle = coinsol.solution.first()
            solution = coinsol.solution.rest().first()

            # work out the deficits between coin amount and expected output for each
            if self.check_is_cc_puzzle(puzzle):
                parent_info = binutils.disassemble(solution.rest().first()).split(' ')
                if len(parent_info) > 1:
                    colour = self.get_genesis_from_puzzle(binutils.disassemble(puzzle))
                    innerpuzzlereveal = solution.rest().rest().rest().first()
                    innersol = solution.rest().rest().rest().rest().first()
                    out_amount = self.get_output_amount_for_puzzle_and_solution(innerpuzzlereveal, innersol)
                    if colour in cc_discrepancy:
                        cc_discrepancy[colour] += coinsol.coin.amount - out_amount
                    else:
                        cc_discrepancy[colour] = coinsol.coin.amount - out_amount
            else:  # standard chia coin
                if None in cc_discrepancy:
                    cc_discrepancy[None] += coinsol.coin.amount - self.get_output_amount_for_puzzle_and_solution(puzzle, solution)
                else:
                    cc_discrepancy[None] = coinsol.coin.amount - self.get_output_amount_for_puzzle_and_solution(puzzle, solution)

        return cc_discrepancy

    # Take an incomplete SpendBundle, fill in auditor information and add missing amounts
    def parse_trade_offer(self, trade_offer):
        spend_bundle = None
        coinsols = []  # [] of CoinSolutions
        cc_coinsol_outamounts = dict()
        # spendslist is [] of (coin, parent_info, outputamount, innersol, innerpuzzlehash=None)
        spendslist = dict()  # used for generating auditor solution
        aggsig = trade_offer.aggregated_signature
        cc_discrepancy = dict()
        chia_discrepancy = 0
        for coinsol in trade_offer.coin_solutions:
            puzzle = coinsol.solution.first()
            solution = coinsol.solution.rest().first()

            # work out the deficits between coin amount and expected output for each
            if self.check_is_cc_puzzle(puzzle):
                parent_info = binutils.disassemble(solution.rest().first()).split(' ')
                if len(parent_info) > 1:
                    colour = self.get_genesis_from_puzzle(binutils.disassemble(puzzle))
                    innerpuzzlereveal = solution.rest().rest().rest().first()
                    innersol = solution.rest().rest().rest().rest().first()
                    out_amount = self.get_output_amount_for_puzzle_and_solution(innerpuzzlereveal, innersol)
                    if colour in cc_discrepancy:
                        cc_discrepancy[colour] += coinsol.coin.amount - out_amount
                    else:
                        cc_discrepancy[colour] = coinsol.coin.amount - out_amount
                    if colour in cc_coinsol_outamounts:
                        cc_coinsol_outamounts[colour].append((coinsol, out_amount))
                    else:
                        cc_coinsol_outamounts[colour] = [(coinsol, out_amount)]
                    parent_info[0] = parent_info[0].replace('(','')
                    parent_info[2] = parent_info[2].replace(')','')
                    if colour in spendslist:
                        spendslist[colour].append((coinsol.coin, parent_info, out_amount, innersol, ProgramHash(Program(innerpuzzlereveal))))
                    else:
                        spendslist[colour] = [(coinsol.coin, parent_info, out_amount, innersol, ProgramHash(Program(innerpuzzlereveal)))]
                else:  # Eve spend - TODO remove support for 0 generation "not my problem"
                    coinsols.append(coinsol)
            else:  # standard chia coin
                chia_discrepancy += self.get_output_discrepancy_for_puzzle_and_solution(coinsol.coin, puzzle, solution)
                coinsols.append(coinsol)

        # make corresponding chia spend
        if chia_discrepancy < 0:
            chia_spends = self.select_coins(abs(chia_discrepancy))
        else:
            chia_spends = set()
            chia_spends.add(self.temp_utxos.pop())

        if chia_spends is None or chia_spends == set():
            return None
        primary_coin = None
        spend_value = sum(x.amount for x in chia_spends)
        for chia_coin in chia_spends:
            if primary_coin is None:
                newpuzhash = self.get_new_puzzlehash()
                primaries = [{'puzzlehash': newpuzhash, 'amount': spend_value + chia_discrepancy}]
                if spend_value + chia_discrepancy > 0:
                    self.temp_utxos.add(Coin(chia_coin, newpuzhash, spend_value + chia_discrepancy))

                solution = self.make_solution(primaries=primaries)
                primary_coin = chia_coin
            else:
                solution = self.make_solution(consumed=[primary_coin.name()])
            pubkey, secretkey = self.get_keys(chia_coin.puzzle_hash)
            puzzle = self.puzzle_for_pk(bytes(pubkey))
            sig = self.get_sigs_for_innerpuz_with_innersol(puzzle, solution)
            aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])

            coinsols.append(CoinSolution(chia_coin, clvm.to_sexp_f([puzzle, solution])))

        # create coloured coin
        for colour in cc_discrepancy.keys():
            coloured_coin = None
            auditor = None
            auditor_innerpuz = None

            if cc_discrepancy[colour] < 0:
                my_cc_spends = self.cc_select_coins_for_colour(colour, abs(cc_discrepancy[colour]))
            else:
                my_cc_spends = self.cc_select_coins_for_colour(colour, 0)

            if (my_cc_spends == [] or my_cc_spends is None) and cc_discrepancy[colour] >= 0:
                self.my_cores.add(self.cc_make_core(colour))
                spend_bundle = self.cc_create_zero_val_for_core(self.cc_make_core(colour))
                for coinsol in spend_bundle.coin_solutions:
                    puzzle = coinsol.solution.first()
                    if coinsol.coin.name() in self.parent_info:
                        my_cc_spends = [Coin(coinsol.coin.name(), coinsol.coin.puzzle_hash, 0)]
                        auditor_innerpuz = coinsol.solution.rest().first().rest().rest().rest().first()
                        break

            if my_cc_spends == [] or my_cc_spends is None:
                return None

            for coloured_coin in my_cc_spends:
                if auditor is None:
                    auditor = coloured_coin
                    if auditor_innerpuz is None:
                        auditor_innerpuz = self.my_coloured_coins[auditor][0]
                    auditor_info = (auditor.parent_coin_info, ProgramHash(auditor_innerpuz), auditor.amount)
                    auditor_formatted = f"(0x{auditor.parent_coin_info} 0x{ProgramHash(auditor_innerpuz)} {auditor.amount})"
                    core = self.cc_make_core(colour)

                else:
                    innersol = self.make_solution(consumed=[auditor.name()])
                    sig = self.get_sigs_for_innerpuz_with_innersol(self.my_coloured_coins[coloured_coin][0], innersol)
                    aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])
                    spendslist[colour].append((coloured_coin, self.parent_info[coloured_coin.parent_coin_info], 0, innersol))

                    innerpuz = binutils.disassemble(self.my_coloured_coins[coloured_coin][0])
                    solution = self.cc_make_solution(core, self.parent_info[coloured_coin.parent_coin_info], coloured_coin.amount, innerpuz, binutils.disassemble(innersol), auditor_info, None)
                    coinsols.append(CoinSolution(coloured_coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coloured_coin][0]), core), solution])))
                    coinsols.append(self.create_spend_for_ephemeral(coloured_coin, auditor, 0))
                    coinsols.append(self.create_spend_for_auditor(auditor, coloured_coin))

            for cc_coinsol_out in cc_coinsol_outamounts[colour]:
                cc_coinsol = cc_coinsol_out[0]
                offer_sol = binutils.disassemble(cc_coinsol.solution)
                # auditor is (primary_input, innerpuzzlehash, amount)
                offer_sol = offer_sol.replace("))) ()) () ()))", f"))) ()) {auditor_formatted} ()))")
                new_coinsol = CoinSolution(cc_coinsol.coin, binutils.assemble(offer_sol))
                coinsols.append(new_coinsol)
                coinsols.append(self.create_spend_for_ephemeral(cc_coinsol.coin, auditor, cc_coinsol_out[1]))
                coinsols.append(self.create_spend_for_auditor(auditor, cc_coinsol.coin))

            newinnerpuzhash = self.get_new_puzzlehash()
            outputamount = sum([c.amount for c in my_cc_spends]) + cc_discrepancy[colour]
            innersol = self.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': outputamount}])
            parent_info = self.parent_info[auditor.parent_coin_info]

            spendslist[colour].append((auditor, self.parent_info[auditor.parent_coin_info], outputamount, innersol, ProgramHash(auditor_innerpuz)))
            sig = self.get_sigs_for_innerpuz_with_innersol(auditor_innerpuz, innersol)
            aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])
            solution = self.cc_make_solution(core, parent_info, auditor.amount, binutils.disassemble(auditor_innerpuz), binutils.disassemble(innersol), auditor_info, spendslist[colour])
            coinsols.append(CoinSolution(auditor, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(auditor_innerpuz), core), solution])))
            coinsols.append(self.create_spend_for_ephemeral(auditor, auditor, outputamount))
            coinsols.append(self.create_spend_for_auditor(auditor, auditor))

        solution_list = CoinSolutionList(coinsols)
        if spend_bundle is None:
            spend_bundle = SpendBundle(solution_list, aggsig)
        else:
            spend_bundle = SpendBundle.aggregate([spend_bundle, SpendBundle(solution_list, aggsig)])
        return spend_bundle

    def get_output_discrepancy_for_puzzle_and_solution(self, coin, puzzle, solution):
        conditions = clvm.run_program(puzzle, solution)[1]
        amount = 0
        while conditions != b'':
            opcode = conditions.first().first()
            if opcode == b'3':
                amount_str = binutils.disassemble(conditions.first().rest().rest().first())
                if amount_str == "()":
                    conditions = conditions.rest()
                    continue
                elif amount_str[0:2] == "0x":
                    amount += int(amount_str, 16)
                else:
                    amount += int(amount_str, 10)
            conditions = conditions.rest()
        discrepancy = coin.amount - amount
        return discrepancy

    def get_output_amount_for_puzzle_and_solution(self, puzzle, solution):
        conditions = clvm.run_program(puzzle, solution)[1]
        amount = 0
        while conditions != b'':
            opcode = conditions.first().first()
            if opcode == b'3':
                amount_str = binutils.disassemble(conditions.first().rest().rest().first())
                if amount_str == "()":
                    conditions = conditions.rest()
                    continue
                elif amount_str[0:2] == "0x":
                    amount += int(amount_str, 16)
                else:
                    amount += int(amount_str, 10)
            conditions = conditions.rest()
        return amount


"""
Copyright 2020 Chia Network Inc
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
