# Coloured Coins

Coloured Coins allow you to create your own uniquely trackable, unforgeable tokens on top of Chia.
You can think of the action of generating coloured coins as marking a certain amount of value with a unique stamp - the value can be moved, rearranged, aggregated or spread, but it will always maintain its stamp.
In this version of coloured coins, value cannot be added to the set after its initial creation, and a coloured coin cannot be burned to reclaim its chia value.

Practically, a coloured coin is composed of two parts.

### Inner Puzzle Hash
A committed "inner" puzzle hash which controls the behaviour of the coin. This works the same way as a standard chia coin's puzzle hash commitment, where the full puzzle and solution are revealed in the solution.

### The Core
The Core controls the colour-related properties of the coin - preventing fraud and ensuring that any coins created from a coloured coin retain the coloured property.
A colour is defined by the ID of the coin that created the initial set of coloured coins.
This genesis coin ID is embedded in the core.
This is the only difference from the core of one coloured coin to the core of a coloured coin of a different colour.

### Value Audits
Because we want to make sure that coloured coins are not being forged later, we need to check the parental lineage.
We assert two things:
1. That we are using the core
2. That our parent is either also using the same core, or is the genesis coin

### Trade Offer
One feature that is unique to coloured coin wallets is their ability to create incomplete transactions which specify how much money they would like to receive at the end of it.
For example you could specify that you want to create a trade where spend 300 coloured coins in return for 1000 chia coins, or you could use it to trade different coloured coins.

This works by creating a spend bundle (a package with a list of spends and an aggregated signature) with output amounts which have the desired excess or deficit. This spend bundle is then serialized into a string of hexdigits which can be shared however the sender likes.
Because this spend bundle contains solutions and signatures, all that a recipient who wishes to accept the offer must do is create the corresponding spends so that the excess and deficits are balanced out.
This completed spend bundle is then pushed to the network and the both parties receive their desired outputs.

## Launching the Wallet
First of all you need to follow the install instructions in the [read-me](../README.md).
As with the other wallets, you need to have an instance of `ledger-sim` running in one window.
To launch the coloured coin wallet run `$ cc_wallet` and it should connect to the instance of ledger-sim that you have running.

## The Coloured Coin Special Options
The main menu should look familiar to the standard wallet but with some extra features.

### Coloured Coin Options
This menu gives you 3 options.
1. Add Core - this lets a wallet know that it should be looking out for a particular coloured coin when it receives information on a new block
2. Generate New Colour - this will spend some chia to create a set of coloured coins. You get asked how many coins of the new colour, and how much value you'd like to give each of them.
3. Print a 0-value Coloured Coin - this takes a colour and will create a new coloured coin of value 0 so that you can create trades of that colour.

### Trade Offer Options
This menu gives you 2 options.
1. Create Offer - This will ask you if you want to use chia as well as coloured coins or just coloured coins. Then it will ask for relative amounts of each kind of coin that you want to spend or gain.
For example putting 100 chia, -60 of a certain coloured coin would mean you were selling 60 coloured coins for 100 chia.
Once you have inputted your trade information, it will generate the trade offer and ask you what file you would like to save it in.
When this file has been saved you are free to distribute it as you please and see if other wallets would like

2. Respond to Offer - This will take a file as input and parse it. It will then parse the trade and present the user with the proposed exchange. If the user accepts these values then the wallet will add spends to the spend bundle completing the trade and then will push the completed spend bundle.
