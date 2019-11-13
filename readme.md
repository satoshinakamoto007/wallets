# Chia Wallets

The Chia Wallets are designed to show off Chia's approach to transactions, and our new language ChiaLisp.
At the moment this project is uses a local server which simulates the full network. This allows us to test the wallet functionality in isolation.

The local server which handles transactions in Chia is called [ledger_sim](https://github.com/Chia-Network/ledger_sim).

## Setup


To install this repository, and all requirements, clone this repository and then run:

```
$ pip install -r requirements.txt
```

To use the QR codes you will also need to support [pyzbar](https://pypi.org/project/pyzbar/).

On Windows this requires no extra effort.

On Linux, run:

```
$ sudo apt-get install libzbar0
$ pip install pyzbar[scripts]
```

On Mac, run:

```
$ brew install zbar
$ pip install pyzbar[scripts]
```

## Using the Command-line Interface

### How to launch

In a terminal window, launch an instance of ledger-sim with:
```
$ ledger-sim
```

The to start a new wallet type:

```
$ python3 wallet_runnable.py
```

Feel free to run more than one instance of the wallet to test sending money between them.

### The Menu

The options available in a standard wallet are:
* **Make Payment** - This will take ask you for an amount to send, and a string of wallet information to generate the address.
* **Get Update** - This will poll the ledger_sim network and find out if there have been any new transactions that concern your wallet.
* **Commit Block / Get Money** - This will create a new block, therefore committing all the pending transactions and also giving your wallet 1000000000 Chia.
* **Print My Details** - This will output a string of information that another wallet can use to send money to you.
* **Set Wallet Name** - This will change how your wallet self-identifies when communicating with other wallets.
* **Make QR code** - This will create a QR code image in the installed folder.
* **Make Smart Contract** - This will allow you to communicate with the Authorised Payees wallet, and send a coin that can only be spent in approved ways. For more information read the [documentation here](./docs/authorised_payees.md).
* **Payment to QR code** - This acts the same way as 'Make Payment' but instead of a string storing the information, it reads in a QR image.
* **Quit** - Closes the wallet program.

## Smart Wallets

The Smart Transactions currently available are:
* **Atomic Swaps** - `$ python3 as_wallet_runnable.py`
* **Authorised Payees** - `$ python3 AP_wallet_runnable.py`
* **Recovery Wallets**
* **Multi-sig Wallet**

For more information about the smart wallets, check out our **[docs](./docs).**
