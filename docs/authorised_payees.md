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

### Menu
