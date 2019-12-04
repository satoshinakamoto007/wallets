# Atomic Swaps

## Background

### Overview

Atomic swaps are processes by which two parties exchange coins using hashed time-locked puzzles, such that no actions by a dishonest party could cause an honest party to end up, at the end of the transaction, in control of coins of fewer value than those which they started with at the beginning of the transaction. In an atomic swap, each party creates a coin in the amount to be exchanged, and the coins are locked both by a hash _h = H(s)_ whose preimage _s_ serves as a key, and by a time limit _t_. Each coin can be spent in one of two ways: either the coin is spent to the intended recipient’s wallet if that recipient provides the secret _s_, or the coin is spent to the coin’s creator’s wallet after time _t_ has passed.

### Setting up an atomic swap

Alice and Bob agree to swap _X_ coins. One party must arbitrarily act as the swap initiator.

Alice initiates the swap by creating a coin _C1_ whose value is _X_ Chia and whose timeout time is _B_ blocks from the current (_NOW_) block height, i.e. at block height _NOW+B_. _C1_ is Alice's "outgoing coin" and Bob's "incoming coin".

Bob adds the swap to his swap list while creating a reciprocal coin _C2_ whose value is _X_ Chia and whose timeout time is _B/2_ from the current (_NOW_) block height, i.e. at block height _(NOW+B)/2_. _C2_ is Bob's "outgoing coin" and Alice's "incoming coin".

_C1_ and _C2_ are committed to the blockchain when the next block is farmed.

### Redeeming atomic swap coins

#### Standard case

In the standard case, Alice will spend her incoming coin (_C2_) to her wallet using the secret _s_, which Alice used to lock her outgoing coin (_C1_). When Alice does this and the spend is posted to the blockchain, _s_ becomes public knowledge. Bob then uses _s_ to spend his incoming coin (_C1_) to his wallet.

#### Timeout case

In the case that Alice fails to spend _C2_ to her wallet before _C2_'s timeout time has elapsed (i.e. when block height _(NOW+B)/2_ is reached), Bob may spend _C2_ back to his wallet. Because Bob does not have the secret _s_, he is unable to spend _C1_ to his wallet. After _C1_'s timeout time has elapsed (i.e. when block height _NOW+B_ is reached), Alice may spend _C1_ back to her wallet.


## Usage

Run a version of `ledger-sim` in a background terminal window.

### Commands
  - 1 Wallet Details / Generate Puzzlehash
  - 2 View Funds
  - 3 View Contacts
  - 4 Add Contacts
  - 5 Edit Contacts
  - 6 View Current Atomic Swaps
  - 7 Initiate Atomic Swap
  - 8 Add Atomic Swap
  - 9 Redeem Atomic Swap Coin
  - 10 Get Update
  - 11 *GOD MODE* Farm Block / Get Money
  - q Quit

### Atomic Swap (step by step)

  Terminal 1 represents Alice's wallet, and Terminal 2 represents Bob's wallet.
  
  1. **RUN**
     - Open two terminal windows.
     - In each window run `$ . .venv/bin/activate`.
     - In each window run `$ as_wallet`.

  2. **Get Chia**
     - **Terminal 1** (Alice's wallet)
       - Type **"11"** and press **enter**. (This gives Alice 1 billion Chia.)
     - **Terminal 2** (Bob's wallet)
       - Type **"11"** and press **enter**. (This gives Bob 1 billion Chia.)

  3. **Atomic Swap**
     - **Terminal 1** (Alice's wallet, which initializes the swap)
       - Type "**7**" and press **enter**.
       - Type "**Bob**" and press **enter**.
     - **Terminal 2** (Bob's wallet, which adds the swap)
       - Type "**8**" and press **enter**.
       - Type "**Alice**" and press **enter**.
     - **Terminal 1**
       - Copy PubKey from **Terminal 1** and then paste it to **Terminal 2** and press **enter**. Go back to **Terminal 1** and press **enter**.
     - **Terminal 2**
       - Copy PubKey from **Terminal 2** and then paste it to **Terminal 1** and press **enter**. Go back to **Terminal 2** and press **enter**.
     - **Terminal 1**
       - Type "**1000**" and press **enter**. (This sets 1000 coins as the amount to be swapped.)
     - **Terminal 2**
       - Type "**1000**" and press **enter**. (This sets 1000 coins as the amount to be swapped.)
     - **Terminal 1**
       - Copy the hash of the secret from **Terminal 1** and then paste it to **Terminal 2** and press **enter** in **Terminal 2**. Go back to **Terminal 1** and press **enter**.
       - Type "**10**" and press **enter**. (This sets 10 blocks as the timelock for Alice's outgoing coin [Bob's incoming coin] and inherently sets 5 blocks as the timelock for Alice's incoming coin [Bob's outgoing coin].)
     - **Terminal 2**
       - Type "**10**" and press **enter**. (This sets 10 blocks as the timelock for Bob's incoming coin [Alice's outgoing coin] and inherently sets 5 blocks as the timelock for Bob's outgoing coin [Alice's incoming coin].)
       - Type "**4**" and press **enter**. (The sets 4 blocks as the minimum buffer time between the timeout blocks of Bob's incoming and outgoing coins.)
     - **Terminal 1**
       - Copy puzzlehash from **Terminal 1** and then paste it to **Terminal 2** and press **enter**. Go back to **Terminal 1** and press **enter**.
     - **Terminal 2**
       - Copy puzzlehash from **Terminal 2** and then paste it to **Terminal 1** and press **enter**. Go back to **Terminal 2** and press **enter**.

  4. **View Swap Info**
     - **Terminal 1**
       - Type "**2**" and press **enter**. (This views the available funds in Alice's wallet. The pending atomic swap coins are marked with an asterisk (*).)
     - **Terminal 2**
       - Type "**2**" and press **enter**. (This views the available funds in Bob's wallet. The pending atomic swap coins are marked with an asterisk (*).)
     - **Terminal 1**
       - Type "**3**" and press **enter**.
       - Type "Bob" and press **enter**. (This views the atomic swap puzzlehashes associated with the Alice's contact "Bob".)
       - Type "**menu**" and press **enter**.
     - **Terminal 2**
       - Type "**3**" and press **enter**.
       - Type "Alice" and press **enter**. (This views the atomic swap puzzlehashes associated with the Bob's contact "Alice".)
       - Type "**menu**" and press **enter**.
     - **Terminal 1**
       - Type "**6**" and press **enter**. (This views the atomic swaps in which Alice is currently participating.)
     - **Terminal 2**
       - Type "**6**" and press **enter**. (This views the atomic swaps in which Bob is currently participating.)
       
  5. **Spend Coins**
     - **Terminal 1**
       - Type "**9**" and press **enter**.
       - Copy the value of "**Atomic swap incoming puzzlehash**" from **Terminal 1** and paste it into **Terminal 1**. Press **enter**.
       - Type "**y**" and press **enter**. (This uses Alice's stored secret to spend Alice's incoming coin.)
       - Type "**11**" and press **enter**. (This farms a new block and includes Alice's spend in that block. At this moment, the secret is revealed publicly and Bob can use it to spend Bob's incoming coin.)
     - **Terminal 2**
       - Type "**10**" and press **enter**. (This updates the latest block information. Bob's wallet pulls from the blockchain the secret from the solution Alice used to spend Alice's incoming coin.)
       - Type "**9**" and press **enter**.
       - Copy the value of "**Atomic swap incoming puzzlehash**" from **Terminal 2** and paste it to **Terminal 2**. Press **enter**.
       - Type "**y**" and press **enter**.
       - type "**11**" and press **enter** (This farms a new block and includes Bob's spend in that block.)
     - **Terminal 1**
       - type "**10**" and press **enter** (Updates lates block info)

  6. **View Swap Info**
     - **Terminal 1**
       - Type "**2**" and press **enter**. (This views the available funds in Alice's wallet. The pending atomic swap coins are gone, and the coin created by Alice's incoming atomic swap coin is there.)
     - **Terminal 2**
       - Type "**2**" and press **enter**. (This views the available funds in Bob's wallet. The pending atomic swap coins are gone, and the coin created by Bob's incoming atomic swap coin is there.)
     - **Terminal 1**
       - Type "**3**" and press **enter**.
       - Type "Bob" and press **enter**. (This views the atomic swap puzzlehashes associated with the Alice's contact "Bob". Alice has no current atomic swap puzzlehashes associated with "Bob".)
       - Type "**menu**" and press **enter**.
     - **Terminal 2**
       - Type "**3**" and press **enter**.
       - Type "Alice" and press **enter**. (This views the atomic swap puzzlehashes associated with the Bob's contact "Alice". Bob has no current atomic swap puzzlehashes associated with "Alice".)
       - Type "**menu**" and press **enter**.
     - **Terminal 1**
       - Type "**6**" and press **enter**. (This views the atomic swaps in which Alice is currently participating. Alice is no longer participating in any atomic swaps.)
     - **Terminal 2**
       - Type "**6**" and press **enter**. (This views the atomic swaps in which Bob is currently participating. Bob is no longer participating in any atomic swaps.)
