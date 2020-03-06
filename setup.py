import setuptools

from clvm_tools.setuptools import build_clvm, monkey_patch

monkey_patch()


setuptools.setup(
    name="wallets",
    description="Chis wallets that interact with ledger-sim",
    author="Chia Network",
    packages=[
        "standard_wallet",
        "utilities",
        "authorised_payees",
        "atomic_swaps",
        "rate_limit",
        "recoverable_wallet",
        "custody_wallet",
        "puzzles",
        "multisig",
    ],
    license="Apache License",
    python_requires=">=3.7, <4",
    entry_points={
        "console_scripts": [
            "wallet = standard_wallet.wallet_runnable:main",
            "ap_wallet = authorised_payees.ap_wallet_runnable:main",
            "as_wallet = atomic_swaps.as_wallet_runnable:main",
            "multisig_wallet = multisig.wallet:main",
            "signer = multisig.signer:main",
            "rl_wallet = rate_limit.rl_wallet_runnable:main",
            "recoverable_wallet = recoverable_wallet.recoverable_wallet_runnable:main",
            "custody_wallet = custody_wallet.custody_wallet_runnable:main",
        ]
    },
    long_description=open("README.md").read(),
    cmdclass={"build_clvm": build_clvm, },
    clvm_extensions=[
        "puzzles/make_p2_delegated_puzzle_or_hidden_puzzle.clvm",
        "puzzles/make_puzzle_m_of_n_direct.clvm",
    ],
    data_files=[
        (
            "puzzles",
            [
                "puzzles/make_p2_delegated_puzzle_or_hidden_puzzle.clvm.hex",
                "puzzles/make_puzzle_m_of_n_direct.clvm.hex",
            ],
        )
    ],
)
