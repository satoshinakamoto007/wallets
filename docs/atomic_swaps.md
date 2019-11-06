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

YouTube walkthrough
https://www.youtube.com/watch?v=oe5kcGsdJqY

### Commands
  - 1 Wallet Details
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
  1. **RUN**
     - Open two terminal windows and run  ``` $ sh atomic_swap.sh ```

  2. **Get Chia**
     - In Both terminals type **"11"** and press **enter** (This will give each wallet 1 million Chia)
  3. **Add Contact**
     - **Terminal 1**
       - type "**4**" and press **enter**
       - Name the Contact:
       - type **"Alice"** and press **enter**
       - PubKey for that contact:
       - Copy PubKey from **Terminal 2** and then paste it to **Terminal 1**. press **enter**.
       - Type **"Menu"** to go back
     - **Terminal 2**
       - type "**4**" and press **enter**
       - Name the Contact:
       - type **"Bob"** and press **enter**
       - PubKey for that contact:
       - Copy PubKey from **Terminal 1** and then paste it to **Terminal 2**. press **enter**.
       - Type **"Menu"** to go back
  4. **Atomic Swap**
     - **Terminal 1** (Initializes)
       - type "**7**" and press **enter**
       - type "**Alice**" and press **enter**
       - type "**1000**" and press **enter** (Select Amount to be swapped)
       - type "**10**" and press **enter** (Select time lock of the swap)
       - type "**password**" and press **enter** (Sets secret that needs to be used in order to spend this coin)
       - [Go To Terminal 2 before proceeding with instructions bellow]
     - **Terminal 2** (Adds)
       - type "**8**" and press **enter**
       - type "**Bob**" and press **enter**
       - type "**1000**" and press **enter** (Select Amount to be swapped)
       - type "**10**" and press **enter** (Select time lock of the swap)
       - copy the value of **"Atomic swap secret hash"** from **Terminal 1** and paste it to **Terminal 2**. Press **enter**
       - copy the value of **"Atomic swap outgoing puzzlehash"** from **Terminal 1** and paste it to **Terminal 2**. Press **enter**.
       - [Go back to **Terminal 1**]
     - **Terminal 1**
       - copy the value of **"Atomic swap outgoing puzzlehash"** from **Terminal 2** and paste it to **Terminal 1**. Press **ENTER**.
     - **Terminal 2**
       - Press **ENTER**
  5. **Get Update**
     - **Terminal 1**
       - type "**11**" and press **enter** (Farms a new block & transaction is included in that block)
       - type "**2**" and press **enter** (View Funds)
     - **Terminal 2**
       - type "**10**" and press **enter** (Updates lates block info)
       - type "**2**" and press **enter** (View Funds)
  6. **Spend Coins**
     - **Terminal 1**
       - type "**9**" and press **enter**
       - Copy the value of "**Atomic swap incoming puzzlehash:**" from **Terminal 1** and paste it into **Terminal 1**. Press **enter**.
       - Type "**y**" and press **enter**. (Use stored secret to spend that coin, At this moment secret is revealed publicly and **Terminal 2** can use it to spend other coin involved in swap)
       - Type "**11**" and press **enter**. (Farms new block)
     - **Terminal 2**
       - type "**10**" and press **enter** (Updates lates block info)
       - type "**9**" and press **enter**
       - copy the value of "**Atomic swap incoming puzzlehash:**" from **Terminal 2** and paste it to **Terminal 2**.Press **enter**.
       - Type "**y**" and press **enter**.
       - Type "**password**" and press **enter**. (Secret was revield publicaly by spending previous coin)
       - Type "**y**" and press **enter**.
       - type "**11**" and press **enter** (Farms a new block & transaction is included in that block)
       - type "**2**" and press **enter** (View Funds)
