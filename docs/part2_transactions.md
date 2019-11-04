# Part 2: Transactions in Chia

This guide directly continues on from [part 1](./part1_basics.md) so if you haven't read that, please do so before reading this.

This section of the guide will cover evaluating a program inside a program, how ChiaLisp relates to transactions and coins on the Chia network, and cover some techniques to create smart transactions using ChiaLisp.
If there are any terms that you aren't sure of, be sure to check the [glossary](./glossary.md).


## Coins and Spends


## Smart Contracts

It is important to remember at this point that the function of ChiaLisp is to write puzzles which lock up coins. When a wallet wants to spend a coin it will submit a solution to the puzzle and the puzzle will either fail immediately or return some conditions which must be met for the transaction to be valid.

* CREATE_COIN - Creates a new output. Specifies a puzzle hash which locks up any funds associated with that id. Also specifies an amount for the new coin.
* ASSERT_MY_COIN_ID - Specifies the id of the puzzle being run.
* INPUT - Specifies an input id which must be spent in this transaction. It may also optionally specify a min_age which must be greater than the time since the input id was created.
* ASSERT_MIN_TIME - Gives a block height which this transaction is not valid before.
* AGG_SIG - Gives a public key and a value hash which must be included in the aggregated signature for this transaction.


### Example: Password Locked Coin
An extremely basic smart coin might be locked up with a password. To implement this we would have the hash of some secret committed and, if presented with the correct secret, instructions to return CREATE_COIN with whatever puzzlehash is provided.
For the following example, the opcode for CREATE_COIN is 0x51, the password is "hello" which has the hash value 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824, and the coin that this will be locked in is of value 100.
The implementation for the above coin would be thus:

```
(i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (c (q 0x51) (c (f (r (a))) (c (q 100) (q ())))) (q -1))
```

To spend this coin a wallet would submit a transaction with the solution (0xmynewpuzzlehash is whatever puzzle they want to lock up their coin with):

```
("hello" 0xmynewpuzzlehash)
```

This would return the following instruction to the environment:

```
(0x51 0xmynewpuzzlehash 100)
```

Which would be interpreted as a valid instruction to create a new coin, locked up with 0xmynewpuzzlehash and with a value of 100.

### Example: Signature Locked Coin

The solution to a puzzle may also be permitted to return conditions to the environment in some situations.
This can be done by embedding a program inside the solution and including instructions to run that program in the puzzle.

It is likely that you will want to ensure that the person submitting the solution is a predetermined public key if this is the case.
We can construct the following smart transaction where AGGSIG is 0x50 and the recipient's pubkey is 0xdeadbeef.
```
(c (c (q 0x50) (c (q 0xdeadbeef) (c (sha256 (wrap (f (a)))) (q ())))) (e (f (a)) (f (r (a)))))
```
The first part of this program will return instructions requiring the environment check that the solution has been signed by the owner of the 0xdeadbeef public key.
The second part will return the results of executing the program inside the solution.

The basic solution for this would look like:
```
((q ((0x51 0xmynewpuzzlehash 50) (0x51 0xanothernewpuzzlehash 50))))
```
