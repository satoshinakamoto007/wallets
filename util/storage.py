from chiasim.storage import RAM_DB


class Storage(RAM_DB):
    def __init__(self, path):
        self._path = path
        self._interested_puzzled_hashes = set()
        self._header_list = []
        super(Storage, self).__init__()

    def add_interested_puzzle_hashes(self, puzzle_hashes):
        self._interested_puzzled_hashes.update(puzzle_hashes)
