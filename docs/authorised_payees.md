# Authorised Payees

An Authorised Payee smart contract means that Wallet A can give Wallet B some money that can only be spent in ways that Wallet A has approved of.

## Overview
The Authorised Payee smart transaction works in the following way.

1. Wallet A asks Wallet B for its public key.
2. Wallet A creates a new Authorised Payee puzzle using Wallet B's public key and locks a new coin up with the puzzle.
3. Wallet A sends Wallet B some information off the blockchain, so that Wallet B is able to detect and use the new coin.
4. Wallet A sends Wallet B some puzzlehashes and as well as a signature for each of the puzzlehashes
5. Wallet B can only spend the coin if it uses one of the approved puzzlehashes and presents the signature in Aggsig.
6. Any change generated to Wallet B will be locked up with the Authorised Payee puzzle.
7. Any wallet can send Wallet B some more money that can only be aggregated into the Authorised Payee coin by using an aggregation puzzle.
8. Wallet A can send additional signatures to Wallet B off the chain at any time it likes.

## Usage

As always, make sure you have a version of ledger-sim running before trying to use the wallets.

One of the unique qualities of the Authorised Payees smart contract is that it is started by a standard wallet, and uses a special wallet to manage the Authorised Payee coin.
You will need to run a standard wallet for setup, as well as an authorised payee wallet for receiving and managing the coin.


1. Launch your authorised payees wallet by running `$ python3 -m authorised_payees/ap_wallet_runnable.py`.
Your public key will be shown, and you will be asked for some setup information.

2. On your standard wallet, first make sure you have some money.
Then from the menu, select `7: Make Smart Contract`, followed by `1: Authorised Payees`.
Paste the AP wallet's public key into the terminal and enter an amount of Chia to send to the AP wallet.
You should then see the initialization string for the Authorised Payee wallet.

3. Paste the initialization string into the AP wallet, and you'll be asked to add an authorised payee as an approved contact.
You can cancel this and do it letter by pressing `q`. Otherwise, we're going to need a 3rd runnable wallet.

4. Start a second standard wallet and from the main menu press `5: Set My Name`, and enter a new name for the wallet.
Then from the menu press `4: Print My Details`.
This should print out some information about the wallet, including a single string, which is used for receiving payments.

5. Paste this single string into the first standard wallet, which we used to create the smart contract.
It should return a `Single string for AP Wallet`. Copy this and paste it into the AP Wallet.

* You can repeat steps 4 and 5 for multiple recipients, but for now we will move on.

6. In one of the wallets you must select `Commit Block` to commit the send to the AP Wallet to the chain.
If you didn't do this from the AP Wallet, then select `4: Get Update` from the AP Wallet's menu.

7. From the main menu in the Authorised Payee wallet, select `2: Make Payment`.
You should see a list of authorised recipients. Enter the name of the recipient you would like to send to.
Then enter the amount you would like to send.

8. Select `Commit Block` from one of the wallets.
If you didn't do this from the recipient wallet you must then select `2: Get Update` from the recipient wallet's menu.
Your new funds should now appear in the recipient wallet's UTXO set.
