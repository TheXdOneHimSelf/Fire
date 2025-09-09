import requests
import io
import random
import chess
import chess.pgn
import chess.polyglot
import chess.variant

VARIANT = "kingofthehill"
TOURNAMENT_IDS = ["cwCZD5Qd", "3T48Bfcb"]
MAX_PLY = 60
MAX_BOOK_WEIGHT = 2520

PGN_OUTPUT = f"{VARIANT}.pgn"
BOOK_OUTPUT = "koth_black.bin"

ALLOWED_BOTS = {"ToromBot", "Speedrunchessgames", "NecroMindX"}


def fetch_tournament_pgn(tournament_id: str) -> str:
    url = f"https://lichess.org/api/tournament/{tournament_id}/games"
    headers = {"Accept": "application/x-chess-pgn"}
    print(f"Downloading PGN for tournament {tournament_id}...")
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text


def save_pgn(text: str, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Saved PGN to {out_path}")


class BookMove:
    def __init__(self):
        self.weight = 0
        self.move: chess.Move | None = None


class BookPosition:
    def __init__(self):
        self.moves: dict[str, BookMove] = {}

    def get_move(self, uci: str) -> BookMove:
        return self.moves.setdefault(uci, BookMove())


class Book:
    def __init__(self):
        self.positions: dict[str, BookPosition] = {}

    def get_position(self, key_hex: str) -> BookPosition:
        return self.positions.setdefault(key_hex, BookPosition())

    def normalize(self):
        for pos in self.positions.values():
            s = sum(bm.weight for bm in pos.moves.values())
            if s <= 0:
                continue
            for bm in pos.moves.values():
                bm.weight = max(1, int(bm.weight / s * MAX_BOOK_WEIGHT))

    def save_polyglot(self, path: str):
        entries = []
        for key_hex, pos in self.positions.items():
            zbytes = bytes.fromhex(key_hex)
            for bm in pos.moves.values():
                if bm.weight <= 0 or bm.move is None:
                    continue
                m = bm.move
                if "@" in m.uci():  # skip drops
                    continue
                mi = m.to_square + (m.from_square << 6)
                if m.promotion:
                    mi += ((m.promotion - 1) << 12)
                mbytes = mi.to_bytes(2, "big")
                wbytes = min(MAX_BOOK_WEIGHT, bm.weight).to_bytes(2, "big")
                lbytes = (0).to_bytes(4, "big")
                entries.append(zbytes + mbytes + wbytes + lbytes)
        entries.sort(key=lambda e: (e[:8], e[10:12]))
        with open(path, "wb") as f:
            for e in entries:
                f.write(e)
        print(f"Saved {len(entries)} moves to book: {path}")


def key_hex(board: chess.Board) -> str:
    return f"{chess.polyglot.zobrist_hash(board):016x}"


def build_book_from_pgn(pgn_path: str, bin_path: str):
    print("Building book from BLACK wins + draws...")
    book = Book()
    with open(pgn_path, "r", encoding="utf-8") as f:
        data = f.read()
    stream = io.StringIO(data)

    processed = 0
    kept = 0
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        variant_tag = (game.headers.get("Variant", "") or "").lower().replace(" ", "")
        if VARIANT not in variant_tag:
            continue

        result = game.headers.get("Result", "")
        black = game.headers.get("Black", "")

        if result not in ("0-1", "1/2-1/2"):
            continue  # only black wins or draws
        if black not in ALLOWED_BOTS:
            continue  # only allowed bots

        kept += 1
        board = chess.variant.KingOfTheHillBoard()

        for ply, move in enumerate(game.mainline_moves()):
            if ply >= MAX_PLY:
                break
            try:
                k = key_hex(board)
                pos = book.get_position(k)
                bm = pos.get_move(move.uci())
                bm.move = move

                decay = max(1, (MAX_PLY - ply) // 5)

                # Emphasize Black moves
                if board.turn == chess.BLACK:
                    bm.weight += 6 * decay
                else:
                    bm.weight += 1  # minimal for context

                board.push(move)
            except Exception:
                break

        processed += 1
        if processed % 100 == 0:
            print(f"Processed {processed} games")

    print(f"Parsed {processed} PGNs, kept {kept} black wins/draws")
    book.normalize()
    for pos in book.positions.values():
        for bm in pos.moves.values():
            bm.weight = min(MAX_BOOK_WEIGHT, bm.weight + random.randint(0, 3))

    book.save_polyglot(bin_path)


def main():
    combined_pgn = ""
    for tid in TOURNAMENT_IDS:
        pgn_text = fetch_tournament_pgn(tid)
        combined_pgn += pgn_text + "\n\n"

    save_pgn(combined_pgn, PGN_OUTPUT)
    build_book_from_pgn(PGN_OUTPUT, BOOK_OUTPUT)
    print("Done.")


if __name__ == "__main__":
    main()
