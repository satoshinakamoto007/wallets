# Part 4: The Compiler and Other Useful Information

In this part of the guide we will cover the compiler, some more examples, and some high level tips for creating programs in ChiaLisp.

## The Compiler

To compile this higher level language in terminal. Firstly install and set up the latest version of [clvm_tools](https://github.com/Chia-Network/clvm_tools).

To compile use:
```
$ run -s2 '(mod (*var names*) (*high level code*))'
```
The compiler has a number of tools that can make writing complex programs more manageable.

### Naming Variables
With variable names it is possible to name the elements that you expect in the solution list.

```
$ run -s2 '(mod (listOfNumbers listOfStrings listOfHex) (c listOfNumbers (c listOfStrings (c listOfHex (q ())))))'
(c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (q ()))))

$ brun '(c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (q ()))))' '((60 70 80) ("list" "of" "strings") (0xf00dbabe 0xdeadbeef 0xbadfeed1))'
((60 70 80) ("list" 28518 "strings") (0xf00dbabe 0xdeadbeef 0xbadfeed1))
```

### Extra Operator: (list)

If we want to create a list during evaluation, you may have noticed we use `(c (A) (c (B) (q ())))`.
This pattern gets messy and hard to follow if extended further than one or two elements.
In the compiler there is support for an extremely convenient operator that creates these complex `c` structures for us.

```
$ run -s2 '(mod (first second) (list 80 first 30 second))' '()'
(c (q 80) (c (f (a)) (c (q 30) (c (f (r (a))) (q ())))))

$ brun '(c (q 80) (c (f (a)) (c (q 30) (c (f (r (a))) (q ())))))' '(120 160)'
(80 120 30 160)
```

Let's put these compiler tricks to use and demonstrate another useful kind of program.

## Iterating Through a List

One of the best uses for recursion is ChiaLisp is looping through a list.

Let's make a program will sum a list of numbers.
Remember `() == 0 == False`

Here we will use `source` to refer to `(f (a))`, and `numbers` to refer to `(f (r (a)))`.

```
(i numbers (+ (f numbers) ((c source (list source (r numbers))))) (q 0))
```
See how much more readable that is?

Let's compile it.
```
$ run -s2 '(mod (source numbers) (i numbers (+ (f numbers) ((c source (list source (r numbers))))) (q 0)))'
(i (f (r (a))) (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ())))))) (q ()))
```

But remember, we need to use lazy evaluation, so let's update that.

```
((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))
```

The next step is to plug it in to our recursive program pattern from [part 3](part3_deeperintoCLVM.md)
```
((c (q ((c (f (a)) (a)))) (c (q (*program*)) (c (f (a)) (q ())))))
```

So the final puzzle for summing a list of numbers in a solution looks like this

```
((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))
```

We now have a program that will sum a list of numbers that works whatever the size of the list.

```
$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((70 80 90 100))'
340

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((35 128 44 100))'
307

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((35))'
35

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '(())'
()

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((100 100 100 100 100 100))'
600
```

## Puzzle Generators and Off-Chain Communication

We have previously looked at the format for a standard transaction for wallets in Chia, however it is important that the wallets support non-standard transactions and also agree what the 'standard' is anyway.

ChiaLisp is very good at creating programs that create programs. We can use this to create Puzzle Generators for the wallets to communicate with.

The puzzle for a standard transaction remains the same except for the public key, so the we can create a program that generates standard puzzles which takes the public key as part of it's solution.

```
$ brun '(c (q 5) (c (c (q 5) (c (q (q 50)) (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (q ((c (sha256tree (f (a))) (q ())))))) (q ())))) (q (((c (f (a)) (f (r (a)))))))))' '("0xpubkey")'
(c (c (q 50) (c (q "0xpubkey") (c (sha256tree (f (a))) (q ())))) ((c (f (a)) (f (r (a))))))
```

This means that wallets can define themselves in terms of what their puzzle generator is.
We don't even need to store or communicate the whole generator!
Because most wallets will be of only a few different types, and wallets will reuse their generator, we can optimise this further by having wallets communicate just the hash of their generator.
We call this the Puzzle Generator ID.

This means that the communication between two wallets during a spend will look like this.

1. Wallet A requests Wallet B's Puzzle Generator ID and a solution which contains their pubkey.
2. Wallet B returns the hash of its puzzle generator and their public key.
3. Wallet A looks up the puzzle generator ID and uses the puzzle generator to generate the puzzlehash
4. Wallet A spends one of their coins to generate a new coin which is locked up with the generated puzzlehash
5. Wallet B detects this new coin and adds it to their list of 'owned' coins
