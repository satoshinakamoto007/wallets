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

## How to launch
In a terminal window, launch an instance of ledger-sim wih:
```
$ ledger-sim
```

The to start a new wallet type:

```
$ python3 wallet_runnable.py
```

## About

The wallets has can be divided into 'standard wallet' functionality and 'smart wallet' functionality, which includes support for smart transactions.

The Smart Transactions currently available are:
* Atomic Swaps
* Authorised Payees
* Recovery Wallets
* Multi-sig

For more information about how these work, check out our other [docs](./docs).

## Making Transactions

Transactions in Chia happen when you specify a current unspent coin
