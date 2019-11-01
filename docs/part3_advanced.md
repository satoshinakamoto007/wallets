# Part 3: Higher Level ChiaLisp

This section of the guide will cover the high level ChiaLisp language, as well as the construction of some smart contracts.
It is important that you are familiar with the previous stages of this guide before reading this part.

Firstly we will cover how to compile from the higher level language into the lower level language.

## Compilation

To compile this higher level language in terminal. Firstly install and set up the latest version of [clvm_tools](https://github.com/Chia-Network/clvm_tools).

To compile use:

`$ run -s2 '(mod ArgumentOrAgumentList (*high level code*))'`

To run the compiled code use:

`$ brun '(*lower level compiled code*)'`

It is recommended that you have some understanding of the CLVM too, to help your understanding


## Programs as Parameters

Unlike most LISP-like languages, ChiaLisp does not allow for user-defined functions.
It does, however, allow programs to be passed as parameters to variables which has similar results.
To execute a program like this reduce must be called again inside the program.
Here is a program that executes the program contained in x0 (a simple doubling operation) using the parameter passed in x1.

```
$ brun '(e (f (a)) (f (r (a))))' '((* (f (a)) (q 2)) (12))'
24
```

This might be a little tricky to understand at first. Remember eval takes two parameters: the code and the new environment.
Recursion
The concept above can be taken further as a program can be passed itself as a parameter, allowing for recursive programs. Here is a factorial program:

```
(if (equal x1 1) 1 (* x1 (eval x0 (list x0 (- x1 1)))))

(e (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) (e (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ()))))))) (a))
```

In this program x0 is the program's own source code, and x1 is the number being operated on. Notice how it call reduce to run x0. Putting it together the result will look like this:

```
$ brun '(e (f (a)) (a))' '((e (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) (e (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ()))))))) (a)) 5)'
120
```

This technique can be used in combination with first, rest, and cons to iterate through lists. Below is a program which iterates through a given list and squares each entry.

```
(if (is_null x1) (list) (cons (* (first x1) (first x1)) (reduce x0 (list x0 (rest x1)))))

(e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q ())) (q (c (* (f (f (r (a)))) (f (f (r (a))))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))
```

Again, x0 is the programs own source code but this time x1 is a list of integers. Running the program looks like this:
```
$ brun '(e (f (a)) (a))' '((e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q ())) (q (c (* (f (f (r (a)))) (f (f (r (a))))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a)) (5 9 4 3 2))'

(25 81 16 9 4)
```

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

## Recursion in Smart Contracts

Now with a basic understanding gathered we can start to build more complex smart transactions.
Remember above how we were able to create recursive programs?
We built those with the assumption that we were in control of the solution as well as the puzzle.
In reality we can only build the puzzle for smart contracts and many people will try to attack it by submitting malicious solutions.
This means we need to improve the security of our recursive programs.
This means that passing the recursive function in as part of the solution will not do.
Instead we should create a new eval environment where the source code is passed in - then call it as a parameter.

```
(e (q (e (f (a)) (a))) (c (q (program)) (c (f (a)) (q ()))))
```

Notice that we need to run e twice. Once to create an environment where the source code exists and once again to run that source code.

This will allow us to create a program that contains other recursive programs inside it.
Recursive programs are useful for instances when you are dealing with lists that you want to loop through.
Some useful recursive programs include:

### Summing integers in a list
```
$ run '(compile (if (not x1) (quote 0) (+ (first x1) (eval x0 (list x0 (rest x1))))))'

(e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q 0)) (q (+ (f (f (r (a)))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))
```

If we put this program inside the recursive wrapper above then we get:

```
$ brun '(e (q (e (f (a)) (a))) (c (q (e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q 0)) (q (+ (f (f (r (a)))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))) (c (f (a)) (q ()))))' '((5 9 3 2 1))'

20
```

### Return some condition for each entry in a list
```
$ run '(compile (if (not x1) (list) (cons (list 0x50 (first x1)) (eval x0 (list x0 (rest x1))))))'

(e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q ())) (q (c (c (q 0x50) (c (f (f (r (a)))) (q ()))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))
```

Plugged into the recursive program wrapper:
```
$ brun '(e (q (e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q ())) (q (c (c (q 6) (c (f (f (r (a)))) (q ()))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))) (c (q (e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (q ())) (q (c (c (q 6) (c (f (f (r (a)))) (q ()))) (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (a))) (c (f (a)) (q ()))))' '((5 9 3 2 1))'

((f 5) (f 9) (f 3) (f 2) (f 1))
```

### Merging two lists together into one

```
$ run '(compile (if (not x1) (first (cons x2 (quote ()))) (eval x0 (list x0 (rest x1) (cons (first x1) x2)))))'

(e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (f (c (f (r (r (a)))) (q ())))) (q (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (q ()))))))) (a))
```

Note that I’m using (first (cons x2 (quote ()))) to return x2. The compiler does not like (q x2) although it would probably work fine in the CLVM. The compiler may change to enable this in the future.

```
$ brun '(e (q (e (f (a)) (a))) (c (q (e (i (e (i (f (r (a))) (q (q ())) (q (q 1))) (a)) (q (f (c (f (r (r (a)))) (q ())))) (q (e (f (a)) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (q ()))))))) (a))) (c (f (a)) (c (f (r (a))) (q ())))))' '((70 80 90) (100 110 120))'

(90 80 70 100 110 120)
```

### Creating Puzzlehashes inside Smart Contracts

It may be the case that you want to create the puzzlehash for a generated coin inside of your ChiaLisp program.
For this purpose it is worth knowing that:

```python
print(ProgramHash(Program(binutils.assemble('(q 10)'))))
```

Is the same as:
```
brun '(sha256 (wrap (q (q 10))))' '()'
```

It is likely that you will want to refer to something inside your solution during the creation of your new puzzle to be hashed.
When generating the puzzlehash of a lock in the Authorized Payee we encounter this problem.
We want to lock up a new coin with the puzzle `(r (c (q ""my_id"") (q ())))` where ""my_id"" is x0 in the solution.
This will evaluate to `()` when ran, but can be reconstructed with just a knowledge of ""my_id"".
This means that we can't simply quote the whole puzzle because if we do then `(f (a))` does not evaluate to ""my_id"", instead it remains in its quoted form `(f (a))`.

This requires the use of quasiquote which actually decompiles into a complicated series of cons boxes.

```
$ brun '(c (q 7) (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (c (q (q ())) (q ())))) (q ())))' '("my_id")'

(r (c (q 0x6d795f6964) (q ())))
```

So finally to generate the puzzlehash we do

```
$ brun '(sha256 (wrap (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (c (q (q ())) (q ())))) (q ())))))' '("my_id")'

0xd4ee414d61686748c8e3b462c054b6490158f9103b4eefbbc5f40fdecfc5d263
```

and to prove it we can test in the Python environment:

```
print(ProgramHash(Program(binutils.assemble('(r (c (q 0x6d795f6964) (q ())))'))))

d4ee414d61686748c8e3b462c054b6490158f9103b4eefbbc5f40fdecfc5d263
```

## Lazy Evaluation in ChiaLisp
It is likely that at some point you will structure your program around one or more if statements. This works fine for many instances, however it may have an unexpected consequence.
$ brun '(i (q 1) (q 100) (x (q "still being evaluated")))'

FAIL: clvm raise (0x7374696c6c206265696e67206576616c7561746564)

This is because ChiaLisp evaluates paths even if they aren't ultimately what is ran, and when x is evaluated it instantly halts the program. To get around this we can use the following design pattern to replace (i A B C).
(e (i A (q B) (q C)) (a))
Applying this to our above example looks like this:
$ brun '(e (i (q 1) (q (q 100)) (q (x (q "still being evaluated")))) (a))'

100

Program Factories inside ChiaLisp
Expanding from the PuzzleHashes Inside ChiaLisp segment - we can now talk about how to develop program factories.
