import cbor

from chiasim.hashable import BLSSignature, CoinSolution, Program


class hexbytes(bytes):
    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<hex:%s>" % self


def remap(s, f):
    if isinstance(s, list):
        return [remap(_, f) for _ in s]
    if isinstance(s, tuple):
        return tuple([remap(_, f) for _ in s])
    if isinstance(s, dict):
        return {remap(k, f): remap(v, f) for k, v in s.items()}
    return f(s)


def use_hexbytes(s):
    def to_hexbytes(s):
        if isinstance(s, bytes):
            return hexbytes(s)
        return s

    return remap(s, to_hexbytes)


def cbor_struct_to_bytes(s):
    def to_bytes(k):
        if hasattr(k, "__bytes__"):
            return bytes(k)
        return k

    return remap(s, to_bytes)


class PartiallySignedTransaction(dict):
    @classmethod
    def from_bytes(cls, blob):
        pst = use_hexbytes(cbor.loads(blob))
        return cls(transform_pst(pst))

    def __bytes__(self):
        cbor_obj = cbor_struct_to_bytes(self)
        return cbor.dumps(cbor_obj)


def xform_aggsig_sig_pair(pair):
    aggsig = BLSSignature.aggsig_pair.from_bytes(pair[0])
    sig = BLSSignature.from_bytes(pair[1])
    return (aggsig, sig)


def xform_list(item_xform):
    def xform(item_list):
        return [item_xform(_) for _ in item_list]

    return xform


PST_TRANSFORMS = dict(
    coin_solutions=xform_list(CoinSolution.from_bytes),
    sigs=xform_list(xform_aggsig_sig_pair),
    delegated_solution=Program.from_bytes,
)


def transform_pst(pst):
    for k, v in PST_TRANSFORMS.items():
        if k in pst:
            pst[k] = v(pst[k])
    return pst
