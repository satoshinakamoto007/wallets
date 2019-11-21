import setuptools

dependencies = ['aiter', 'blspy', 'cbor']

setuptools.setup(
   name='wallets',
   version='1.0',
   description='Chis wallets that interact with ledger-sim',
   author='Chia Network',
   packages=['standard_wallet', 'utilities', 'authorised_payees', 'atomic_swaps', 'rate_limit'],
   license='Apache License',
   python_requires='>=3.7, <4',
   entry_points={
        'console_scripts':
            [
                'wallet = standard_wallet.wallet_runnable:main',
                'ap_wallet = authorised_payees.ap_wallet_runnable:main',
                'as_wallet = atomic_swaps.as_wallet_runnable:main',
                'rl_wallet = rate_limit.rl_wallet_runnable:main',
            ]
        },
   install_requires=dependencies,
   long_description=open('README.md').read()
)
