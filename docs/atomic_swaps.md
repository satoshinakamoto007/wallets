# Atomic Swaps

Run script will run ledger-sim in the background and launch atomic swap wallet in the terminal.


### Usage

YouTube walkthrough
https://www.youtube.com/watch?v=oe5kcGsdJqY

#### Commands
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

#### Atomic Swap (step by step)
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
