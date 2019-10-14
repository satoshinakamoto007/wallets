# Chia Wallets

### Simulators

The simulators automatically generate transactions back and forth between two wallets and don't require any input once they've been set going.

### Runnable Wallets

Runnable wallets use a menu with user input. They require a running an instance of [ledger_sim](https://github.com/Chia-Network/ledger_sim) for the wallets to connect to.

The QR code functionality relies on [https://github.com/NaturalHistoryMuseum/pyzbar/](pyzbar)
```bash
brew install zbar
```

New block commits are done on command from one of the wallets, so make sure you that you make a new block after your transaction.
Other wallets, similarly, must request an update once it exists.
TODO: - this is scheduled to change into neutrino filters soon.
