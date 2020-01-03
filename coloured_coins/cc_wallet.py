from standard_wallet.wallet import Wallet


class CCWallet(Wallet):
    cores = []

    def __init__():
        return

    def notify(self, additions, deletions):
        super().notify(additions, deletions)
        self.cc_notify(additions)

    def cc_notify(self, additions):
        for coin in additions:
            self.cc_verify_lineage()
        return

    def cc_verify_lineage(self):
        return

    # This is for generating a new set of coloured coins - this may be moved out of this wallet
    def cc_generate_spend_for_genesis_coins():

        spend_bundle = None
        return spend_bundle

    # This is for spending an existing coloured coin
    def cc_make_puzzle(self, innerpuz):
        core = self.cc_make_core()
        puz = f"(c {core} ((c {innerpuz} (f (r (r (r (a))))))))"
        return puz

    # TODO: Ask Bram about this - core is "the colour"
    # Actually a colour specific filter program that checks parents - what format?
    def cc_make_core(self):
        core = ""
        return core

    # This is for spending a recieved coloured coin
    def cc_make_solution(self, core, parent_info, innerpuz, innersol):
        if isinstance(parent_info, list):
            parent_info = f"({parent_info[0]} {parent_info[1]} {parent_info[2]})"
        elif parent_info == "'origin'"

        sol = f"({core} {parent_info}"
        return sol

    # This is for spending a recieved coloured coin
    def cc_generate_signed_transaction(self):
        spend_bundle = None
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
