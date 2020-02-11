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
        self.my_cores = []  # core is stored as a string
        self.my_coloured_coins = dict()  # {coin: (innerpuzzle, core)}
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
                        result = clvm.eval_f(clvm.eval_f, body.solution_program, binutils.assemble("()"))
                        while result != b'':
                            tuple = result.first()
                            if tuple.first() == coin.name():
                                puzzle = tuple.rest().first().first()
                                if self.check_is_cc_puzzle(puzzle):
                                    innerpuzhash = binutils.disassemble(puzzle)[9:75]
                                    self.parent_info[coin.name()] = (coin.parent_coin_info, innerpuzhash, coin.amount)
                                else:
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
        genesisCoin = puzstring[-602:].split(')')[0]
        if all(c in string.hexdigits for c in genesisCoin) is not True:
            return False
        if self.cc_make_puzzle(innerpuz, self.cc_make_core(genesisCoin)) == puzzle:
            return True
        else:
            return False

    def cc_can_generate(self, finalpuzhash):
        for i in reversed(range(self.next_address)):
            innerpuzhash = ProgramHash(puzzle_for_pk(bytes(self.extended_secret_key.public_child(i))))
            for core in self.my_cores:
                if ProgramHash(self.cc_make_puzzle(innerpuzhash, core)) == finalpuzhash:
                    return True
        return False

    def cc_add_core(self, core):
        self.my_cores.append(core)
        return

    # This is for generating a new set of coloured coins
    def cc_generate_spend_for_genesis_coins(self, amounts, genesisCoin=None):
        total_amount = sum(amounts)
        if genesisCoin is None:
            my_utxos_copy = self.temp_utxos.copy()
            genesisCoin = my_utxos_copy.pop()
            while genesisCoin.amount < total_amount and len(my_utxos_copy) > 0:
                genesisCoin = my_utxos_copy.pop()
            if genesisCoin.amount < total_amount:
                return None  # no reason why a coin couldn't have two parents, just want to make debugging simple for now
        core = self.cc_make_core(genesisCoin.name())
        self.cc_add_core(core)
        spends = []
        change = genesisCoin.amount - total_amount

        # Aped from wallet.generate_unsigned_transaction()
        pubkey, secretkey = self.get_keys(genesisCoin.puzzle_hash)

        puzzle = self.puzzle_for_pk(bytes(pubkey))
        primaries = []
        for amount in amounts:
            innerpuzhash = self.get_new_puzzlehash()
            newpuzzle = self.cc_make_puzzle(innerpuzhash, core)
            newpuzzlehash = ProgramHash(newpuzzle)
            primaries.append({'puzzlehash': newpuzzlehash, 'amount': amount})
        if change > 0:
            changepuzzlehash = self.get_new_puzzlehash()
            primaries.append(
                {'puzzlehash': changepuzzlehash, 'amount': change})
            # add change coin into temp_utxo set
            self.temp_utxos.add(Coin(genesisCoin, changepuzzlehash, change))
        solution = self.make_solution(primaries=primaries)
        spends.append((puzzle, CoinSolution(genesisCoin, solution)))
        self.temp_balance -= total_amount

        return self.sign_transaction(spends)

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
        assert_my_parent_is_origin = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (f (r (a))) (sha256tree {add_core_to_my_innerpuz_reveal}) (uint64 (f (r (r (a)))))) (q ())))"

        assert_my_parent_follows_core_logic = f"(c (q 0x{ConditionOpcode.ASSERT_MY_COIN_ID.hex()}) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree {add_core_to_parent_innerpuzhash}) (uint64 (f (r (r (f (r (a)))))))) (sha256tree {add_core_to_my_innerpuz_reveal}) (uint64 (f (r (r (a)))))) (q ())))"

        # heritage_check = f"((c (i (l (f (r (a)))) (q {assert_my_parent_follows_core_logic}) (q ((c (i (= (q 0x{originID}) (f (r (a)))) (q {assert_my_parent_is_origin}) (q (x))) (a)))) ) (a)))"

        add_core_to_auditor_innerpuzhash = f"(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (r (r (r (r (a))))))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))"
        create_a_puz_for_cn = f"(c (q #r) (c (c (q #c) (c (c (q #q) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree {add_core_to_parent_innerpuzhash}) (uint64 (f (r (r (f (r (a)))))))) (sha256tree {add_core_to_my_innerpuz_reveal}) (uint64 (f (r (r (a)))))) (q ()))) (q ((q ()))))) (q ())))"

        consume_a = f"(c (q 52) (c (sha256 (sha256 (f (f (r (r (r (r (r (a)))))))) (sha256tree {add_core_to_auditor_innerpuzhash}) (uint64 (f (r (r (f (r (r (r (r (r (a)))))))))))) (sha256tree {create_a_puz_for_cn}) (uint64 (q 0))) (q ())))"

        create_e_puz = f"(c (q #r) (c (c (q #r) (c (c (q #c) (c (c (q #q) (c (sha256 (f (f (r (r (r (r (r (a)))))))) (sha256tree {add_core_to_auditor_innerpuzhash}) (uint64 (f (r (r (f (r (r (r (r (r (a)))))))))))) (q ()))) (c (c (q #c) (c (c (q #uint64) (c (c (q #q) (c {sum_outputs} (q ()))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ())))"
        create_e = f"(c (q 51) (c (sha256tree {create_e_puz}) (c (uint64 (q 0)) (q ()))))"

        consume_es_generate_as = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c (c (c (q 51) (c (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256 (f (f (f (r (a))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (uint64 (f (r (r (f (f (r (a))))))))) (q ()))) (q ((q ()))))) (q ())))) (q (0x0000000000000000)))) (c (c (q 52) (c (sha256 (sha256 (f (f (f (r (a))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (f (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (uint64 (f (r (r (f (f (r (a))))))))) (sha256tree (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (c (c (q 5) (c (c (q 20) (c (c (q 1) (c (f (r (r (r (f (f (r (a)))))))) (q ()))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ())))) (q 0x0000000000000000)) (q ()))) (f (r (r (r (r (a)))))))) (q ()))))))))) (q (f (r (r (r (r (a)))))))) (a))))(c (f (r (r (r (r (r (r (a)))))))) (c (sha256 (sha256 (f (f (r (a)))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (f (r (a))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (uint64 (f (r (r (f (r (a)))))))) (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256tree (f (r (r (r (a)))))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((a))))) (q ())) (q ())))) (q ())))) (uint64 (f (r (r (a)))))) (c (f (a)) (q (()))))))))"

        compare_sums = f"((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (a))))) (c (+ (f (r (r (r (f (f (r (a)))))))) (f (r (r (r (a)))))) (q ())))))))) (q (= (f (r (r (a)))) (f (r (r (r (a)))))))) (a)))) (c (f (r (r (r (r (r (r (a)))))))) (q (() ()))))))"

        auditor_code_path = f"((c (i (f (r (r (r (r (r (r (a)))))))) (q ((c (i {compare_sums} (q {consume_es_generate_as}) (q (x))) (a)))) (q (q ()))) (a)))"

        normal_case = f"(c {consume_a} (c {create_e} (c {assert_my_parent_follows_core_logic} {self.merge_two_lists(replace_generated_createcoins, auditor_code_path)})))"

        create_child_with_my_puzzle = f"(c (q 51) (c (sha256tree {add_core_to_my_innerpuz_reveal}) (c (uint64 (f (r (r (a))))) (q ()))))"
        eve_case = f"((c (i (= (q 0x{originID}) (f (r (a)))) (q (c {assert_my_parent_is_origin} (c {create_child_with_my_puzzle} (q ())))) (q (x))) (a)))"
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
        innerpuz = binutils.disassemble(self.my_coloured_coins[auditor][0])
        core = self.my_coloured_coins[auditor][1]
        auditor_info = (auditor.parent_coin_info, ProgramHash(self.my_coloured_coins[auditor][0]), auditor.amount)
        list_of_solutions = []
        for spend in spendslist:
            coin = spend[0]
            innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])
            innersol = spend[3]
            parent_info = spend[1]
            solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), auditor_info, None)
            list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution])))
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
        #breakpoint()

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
            #breakpoint()
        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def create_spend_for_ephemeral(self, parent_of_e, auditor_coin, spend_amount):
        puzstring = f"(r (r (c (q 0x{auditor_coin.name()}) (c (uint64 (q {spend_amount})) (q ())))))"
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

    # This creates an incomplete/incorrect spend SpendBundle
    # solution is missing auditor info, output amount != input amount
    def create_trade_offer(self, chiacoin, amount, ccspendslist, sigs=[]):
        # ccspendslist is [] of (coin, parent_info, outputamount, innersol)
        core = self.my_coloured_coins[ccspendslist[0][0]][1]
        list_of_solutions = []
        for spend in ccspendslist:
            coin = spend[0]
            innerpuz = binutils.disassemble(self.my_coloured_coins[coin][0])
            innersol = spend[3]
            parent_info = spend[1]
            solution = self.cc_make_solution(core, parent_info, coin.amount, innerpuz, binutils.disassemble(innersol), None, None)
            list_of_solutions.append(CoinSolution(coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coin][0]), core), solution])))

        # standard coin CoinSolution generation
        newpuzhash = self.get_new_puzzlehash()
        solution = self.make_solution(primaries=[{'puzzlehash': newpuzhash, 'amount': amount}])
        pubkey, secretkey = self.get_keys(chiacoin.puzzle_hash)
        puzzle = self.puzzle_for_pk(bytes(pubkey))
        list_of_solutions.append(CoinSolution(chiacoin, clvm.to_sexp_f([puzzle, solution])))
        sigs = sigs + self.get_sigs_for_innerpuz_with_innersol(puzzle, solution)

        solution_list = CoinSolutionList(list_of_solutions)
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(solution_list, aggsig)

        return spend_bundle

    # Take an incomplete SpendBundle, fill in auditor information and add missing amounts
    def parse_trade_offer(self, trade_offer):
        coinsols = []  # [] of CoinSolutions
        cc_coinsol_outamounts = []
        # spendslist is [] of (coin, parent_info, outputamount, innersol, innerpuzzlehash=None)
        spendslist = []  # used for generating auditor solution
        aggsig = trade_offer.aggregated_signature
        cc_discrepancy = 0
        chia_discrepancy = 0
        for coinsol in trade_offer.coin_solutions:
            puzzle = coinsol.solution.first()
            solution = coinsol.solution.rest().first()

            # work out the deficits between coin amount and expected output for each
            if self.check_is_cc_puzzle(puzzle):  # CC or chia? - TODO: make more nuanced
                innerpuzzlereveal = solution.rest().rest().rest().first()
                innersol = solution.rest().rest().rest().rest().first()
                out_amount = self.get_output_amount_for_puzzle_and_solution(coinsol.coin, innerpuzzlereveal, innersol)
                cc_discrepancy += coinsol.coin.amount - out_amount
                cc_coinsol_outamounts.append((coinsol, out_amount))
                parent_info = binutils.disassemble(solution.rest().first()).split(' ')
                parent_info[0] = parent_info[0].replace('(','')
                parent_info[2] = parent_info[2].replace(')','')
               #breakpoint()
                spendslist.append((coinsol.coin, parent_info, self.get_output_amount_for_puzzle_and_solution(coinsol.coin, innerpuzzlereveal, innersol), innersol, ProgramHash(Program(innerpuzzlereveal))))
            else:  # standard chia coin
                chia_discrepancy += self.get_output_discrepancy_for_puzzle_and_solution(coinsol.coin, puzzle, solution)
                coinsols.append(coinsol)

        # make corresponding chia spend
        chia_coin = None
        if chia_discrepancy < 0:
            for utxo in self.temp_utxos:
                #breakpoint()
                if utxo.amount + chia_discrepancy >= 0:
                    #breakpoint()
                    chia_coin = utxo
                    break
            self.temp_utxos.remove(chia_coin)
        else:
            chia_coin = self.temp_utxos.pop()

        if chia_coin is None:
            return None
        # TODO: this could be done with multiple coins and assert_consumed in the future, but for now...

        solution = self.make_solution(primaries=[{'puzzlehash': self.get_new_puzzlehash(), 'amount': chia_coin.amount + chia_discrepancy}])
        pubkey, secretkey = self.get_keys(chia_coin.puzzle_hash)
        puzzle = self.puzzle_for_pk(bytes(pubkey))
        sig = self.get_sigs_for_innerpuz_with_innersol(puzzle, solution)
        #breakpoint()
        aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])

        coinsols.append(CoinSolution(chia_coin, clvm.to_sexp_f([puzzle, solution])))
        #breakpoint()

        # create coloured coin
        coloured_coin = None
        if cc_discrepancy < 0:
            for utxo in list(self.my_coloured_coins.keys()):
                #breakpoint()
                if utxo.amount + cc_discrepancy >= 0:
                    #breakpoint()
                    coloured_coin = utxo
                    break
        else:
            coloured_coin = list(self.my_coloured_coins.keys()).copy().pop()

        if coloured_coin is None:
            return None
        # TODO: support multiple coloured coins in same spend

        newinnerpuzhash = self.get_new_puzzlehash()
        outputamount = coloured_coin.amount + cc_discrepancy
        innersol = self.make_solution(primaries=[{'puzzlehash': newinnerpuzhash, 'amount': outputamount}])
        sig = self.get_sigs_for_innerpuz_with_innersol(self.my_coloured_coins[coloured_coin][0], innersol)
        aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])

        # now to make solution so that cc_coinsols and new coin play nicely

        spendslist.append((coloured_coin, self.parent_info[coloured_coin.parent_coin_info], outputamount, innersol))
        auditor = coloured_coin
        core = self.my_coloured_coins[auditor][1]
        auditor_info = (auditor.parent_coin_info, ProgramHash(self.my_coloured_coins[auditor][0]), auditor.amount)
        innerpuz = binutils.disassemble(self.my_coloured_coins[coloured_coin][0])

        for cc_coinsol_out in cc_coinsol_outamounts:
            cc_coinsol = cc_coinsol_out[0]
            offer_sol = binutils.disassemble(cc_coinsol.solution)
            # auditor is (primary_input, innerpuzzlehash, amount)
            auditor_formatted = f"(0x{auditor.parent_coin_info} 0x{ProgramHash(self.my_coloured_coins[coloured_coin][0])} {auditor.amount})"
            offer_sol = offer_sol.replace("))) ()) () ()))", f"))) ()) {auditor_formatted} ()))")
            new_coinsol = CoinSolution(cc_coinsol.coin, binutils.assemble(offer_sol))
            coinsols.append(new_coinsol)
            coinsols.append(self.create_spend_for_ephemeral(cc_coinsol.coin, auditor, cc_coinsol_out[1]))
            coinsols.append(self.create_spend_for_auditor(auditor, cc_coinsol.coin))
            #breakpoint()

        parent_info = self.parent_info[coloured_coin.parent_coin_info]
        solution = self.cc_make_solution(core, parent_info, coloured_coin.amount, innerpuz, binutils.disassemble(innersol), auditor_info, spendslist)
        coinsols.append(CoinSolution(coloured_coin, clvm.to_sexp_f([self.cc_make_puzzle(ProgramHash(self.my_coloured_coins[coloured_coin][0]), core), solution])))
        coinsols.append(self.create_spend_for_ephemeral(coloured_coin, auditor, outputamount))
        coinsols.append(self.create_spend_for_auditor(auditor, coloured_coin))
        #breakpoint()
        solution_list = CoinSolutionList(coinsols)
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def get_output_discrepancy_for_puzzle_and_solution(self, coin, puzzle, solution):
        conditions = clvm.eval_f(clvm.eval_f, puzzle, solution)
        amount = 0
        while conditions != b'':
            opcode = conditions.first().first()
            if opcode == b'3':
                amount_str = binutils.disassemble(conditions.first().rest().rest().first())
                if amount_str[0:2] == "0x":
                    amount += int(amount_str, 16)
                else:
                    amount += int(amount_str, 10)
            conditions = conditions.rest()
        discrepancy = coin.amount - amount
        return discrepancy

    def get_output_amount_for_puzzle_and_solution(self, coin, puzzle, solution):
        conditions = clvm.eval_f(clvm.eval_f, puzzle, solution)
        amount = 0
        while conditions != b'':
            opcode = conditions.first().first()
            if opcode == b'3':
                amount_str = binutils.disassemble(conditions.first().rest().rest().first())
                if amount_str[0:2] == "0x":
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
