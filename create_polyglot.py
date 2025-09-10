import chess
import chess.pgn
import chess.polyglot

MAX_BOOK_PLIES = 20
MAX_BOOK_WEIGHT = 10000

def format_zobrist_key_hex(zobrist_key):
    return f"{zobrist_key:016x}"

def get_zobrist_key_hex(board):
    return format_zobrist_key_hex(chess.polyglot.zobrist_hash(board))

class BookMove:
    def __init__(self):
        self.weight = 0
        self.move = None

class BookPosition:
    def __init__(self):
        self.moves = {}

    def get_move(self, uci):
        return self.moves.setdefault(uci, BookMove())

class Book:
    def __init__(self):
        self.positions = {}

    def get_position(self, zobrist_key_hex):
        return self.positions.setdefault(zobrist_key_hex, BookPosition())

    def normalize_weights(self):
        for pos in self.positions.values():
            total_weight = sum(bm.weight for bm in pos.moves.values())
            if total_weight > 0:
                for bm in pos.moves.values():
                    bm.weight = int(bm.weight / total_weight * MAX_BOOK_WEIGHT)

    def save_as_polyglot(self, path):
        with open(path, 'wb') as outfile:
            entries = []
            for key_hex, pos in self.positions.items():
                zbytes = bytes.fromhex(key_hex)
                for uci, bm in pos.moves.items():
                    if bm.weight <= 0:
                        continue
                    move = bm.move
                    mi = move.to_square + (move.from_square << 6)
                    if move.promotion:
                        mi += ((move.promotion - 1) << 12)
                    mbytes = mi.to_bytes(2, byteorder="big")
                    wbytes = bm.weight.to_bytes(2, byteorder="big")
                    lbytes = (0).to_bytes(4, byteorder="big")
                    entries.append(zbytes + mbytes + wbytes + lbytes)

            entries.sort(key=lambda e: (e[:8], e[10:12]))
            for entry in entries:
                outfile.write(entry)
            print(f"✅ Saved {len(entries)} moves to book: {path}")

class LichessGame:
    def __init__(self, game):
        self.game = game

    def result(self):
        return self.game.headers.get("Result", "*")

    def score(self, board):
        """Return score depending on Antichess rules (side to move should want to LOSE pieces)."""
        res = self.result()
        if res == "1-0":
            return 2 if board.turn == chess.WHITE else 0
        if res == "0-1":
            return 2 if board.turn == chess.BLACK else 0
        if res == "1/2-1/2":
            return 1
        return 0

def build_book_file(pgn_path, book_path):
    book = Book()
    with open(pgn_path) as pgn_file:
        for i, game in enumerate(iter(lambda: chess.pgn.read_game(pgn_file), None), start=1):
            if i % 100 == 0:
                print(f"Processed {i} games")
            if game is None:
                break
            if game.headers.get("Variant", "").lower() != "antichess":
                continue

            ligame = LichessGame(game)
            board = game.board()
            ply = 0
            for move in game.mainline_moves():
                if ply >= MAX_BOOK_PLIES:
                    break
                zobrist_key_hex = get_zobrist_key_hex(board)
                position = book.get_position(zobrist_key_hex)
                bm = position.get_move(move.uci())
                bm.move = move
                bm.weight += ligame.score(board)
                board.push(move)
                ply += 1

    book.normalize_weights()
    book.save_as_polyglot(book_path)

if __name__ == "__main__":
    build_book_file("antichess_games.pgn", "anti_book.bin")
