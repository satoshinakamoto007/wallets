import pkg_resources
import os
import sys

from chiasim.hashable import Program


def path_list_for_filename(filename):
    yield pkg_resources.resource_filename(__name__, "%s.hex" % filename)
    yield "%s/%s.hex" % (sys.prefix, filename)

    # TODO: try to compile it


def load_clvm(filename):
    for p in path_list_for_filename(filename):
        if os.path.isfile(p):
            break

    clvm_hex = open(p, "rt").read()
    clvm_blob = bytes.fromhex(clvm_hex)
    return Program.from_bytes(clvm_blob)
