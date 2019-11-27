from binascii import hexlify
from blspy import PublicKey, PrependSignature
import string
from chiasim.hashable import ProgramHash, BLSSignature


def pubkey_format(pubkey):
    if isinstance(pubkey, str):
        if len(pubkey) == 96:
            if not check_string_is_hex(pubkey):
                raise ValueError
            ret = "0x" + pubkey
        elif len(pubkey) == 98:
            if not check_string_is_hex(pubkey[2:95]):
                raise ValueError
            if not pubkey[0:2] == "0x":
                raise ValueError
            ret = pubkey
        else:
            raise ValueError
    elif hasattr(pubkey, 'decode'):  # check if serialized
        ret = serialized_key_to_string(pubkey)
    elif isinstance(pubkey, PublicKey):
        ret = serialized_key_to_string(pubkey.serialize())
    return ret


def serialized_key_to_string(pubkey):
    return "0x%s" % hexlify(pubkey).decode('ascii')


def check_string_is_hex(value):
    for letter in value:
        if letter not in string.hexdigits:
            return False
    return True


def puzzlehash_from_string(puzhash):
    return ProgramHash(bytes.fromhex(puzhash))


def pubkey_from_string(pubkey):
    return PublicKey.from_bytes(bytes.fromhex(pubkey))


def signature_from_string(signature):
    sig = PrependSignature.from_bytes(bytes.fromhex(signature))
    # sig.sig = bytes(signature)
    return sig


def BLSSignature_from_string(signature):
    return BLSSignature(bytes.fromhex(signature))


"""
Copyright 2018 Chia Network Inc
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
