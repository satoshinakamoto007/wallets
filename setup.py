import setuptools

dependencies = ['aiter', 'blspy', 'cbor', 'qrcode', 'pyzbar', 'Pillow']

setuptools.setup(
   name='wallets',
   version='1.0',
   description='Wallet programs that interact with ledger-sim',
   author='Chia Network',
   packages=['standard_wallet', 'utilities', 'authorised_payees', 'atomic_swaps'],
   license='Apache License',
   python_requires='>=3.7, <4',
   install_requires=dependencies,
   long_description=open('README.md').read()
)
