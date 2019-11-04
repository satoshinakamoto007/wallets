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



# TODO - Program Factories inside ChiaLisp
Expanding from the PuzzleHashes Inside ChiaLisp segment - we can now talk about how to develop program factories.
