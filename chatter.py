import os
import platform
from collections import defaultdict
import psutil
import random

from api import API
from botli_dataclasses import Chat_Message, Game_Information
from config import Config
from lichess_game import Lichess_Game


class Chatter:
    def __init__(self,
                 api: API,
                 config: Config,
                 username: str,
                 game_information: Game_Information,
                 lichess_game: Lichess_Game
                 ) -> None:
        self.api = api
        self.username = username
        self.game_info = game_information
        self.lichess_game = lichess_game

        # --- Engine always recognized as Nothing_V-2.21 ---
        class DummyOpponent:
            is_engine = False
            rating = None

        class DummyEngine:
            name = "Nothing_V-2.21"
            opponent = DummyOpponent()

        self.lichess_game.engine = DummyEngine()
        # ---------------------------------------------------

        self.opponent_username = self.game_info.black_name if lichess_game.is_white else self.game_info.white_name
        self.cpu_message = self._get_cpu()
        self.draw_message = self._get_draw_message(config)
        self.name_message = self._get_name_message(config.version)
        self.ram_message = self._get_ram()
        self.player_greeting = self._format_message(config.messages.greeting)
        self.player_goodbye = self._format_message(config.messages.goodbye)
        self.spectator_greeting = self._format_message(config.messages.greeting_spectators)
        self.spectator_goodbye = self._format_message(config.messages.goodbye_spectators)
        self.print_eval_rooms: set[str] = set()

    async def handle_chat_message(self, chatLine_Event: dict, takeback_count: int, max_takebacks: int) -> None:
        chat_message = Chat_Message.from_chatLine_event(chatLine_Event)

        if chat_message.username == 'lichess':
            if chat_message.room == 'player':
                print(chat_message.text)
            return

        if chat_message.username != self.username:
            prefix = f'{chat_message.username} ({chat_message.room}): '
            output = prefix + chat_message.text
            if len(output) > 128:
                output = f'{output[:128]}\n{len(prefix) * " "}{output[128:]}'

            print(output)

        if chat_message.text.startswith('!'):
            await self._handle_command(chat_message, takeback_count, max_takebacks)

    async def print_eval(self) -> None:
        if not self.game_info.increment_ms and self.lichess_game.own_time < 30.0:
            return

        for room in self.print_eval_rooms:
            await self._send_last_message(room)

    async def send_greetings(self) -> None:
        if self.player_greeting:
            await self.api.send_chat_message(self.game_info.id_, 'player', self.player_greeting)

        if self.spectator_greeting:
            await self.api.send_chat_message(self.game_info.id_, 'spectator', self.spectator_greeting)

    async def send_goodbyes(self) -> None:
        if self.lichess_game.is_abortable:
            return

        if self.player_goodbye:
            await self.api.send_chat_message(self.game_info.id_, 'player', self.player_goodbye)

        if self.spectator_goodbye:
            await self.api.send_chat_message(self.game_info.id_, 'spectator', self.spectator_goodbye)

    async def send_abortion_message(self) -> None:
        await self.api.send_chat_message(self.game_info.id_, 'player', ('Too bad you weren\'t there. '
                                                                        'Feel free to challenge me again, '
                                                                        'I will accept the challenge if possible.'))

    async def _handle_command(self, chat_message: Chat_Message, takeback_count: int, max_takebacks: int) -> None:
        command = chat_message.text[1:].lower()

        match command:
            case 'cpu':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.cpu_message)
            case 'draw':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.draw_message)
            case 'eval':
                await self._send_last_message(chat_message.room)
            case 'motor':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.lichess_game.engine.name)
            case 'name':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.name_message)
            case 'ping':
                if not self.game_info.increment_ms and self.lichess_game.own_time < 10.0:
                    return

                ping = await self.api.ping() * 1000.0
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, f'Ping: {ping:.1f} ms')
            case 'printeval':
                if not self.game_info.increment_ms and self.game_info.initial_time_ms < 180_000:
                    await self._send_last_message(chat_message.room)
                    return

                if chat_message.room in self.print_eval_rooms:
                    return

                self.print_eval_rooms.add(chat_message.room)
                await self.api.send_chat_message(self.game_info.id_,
                                                 chat_message.room,
                                                 'Type !quiet to stop eval printing.')
                await self._send_last_message(chat_message.room)
            case 'quiet':
                self.print_eval_rooms.discard(chat_message.room)
            case 'pv':
                if chat_message.room == 'player':
                    return

                if not (message := self._append_pv()):
                    message = 'No PV available.'

                await self.api.send_chat_message(self.game_info.id_, chat_message.room, message)
            case 'ram':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.ram_message)
            case 'takeback':
                await self._send_takeback_message(chat_message.room, takeback_count, max_takebacks)
            case 'help' | 'commands':
                help_msg = (
                    "Supported commands:\n"
                    "!cpu - Show CPU information\n"
                    "!ram - Show RAM information\n"
                    "!motor - Show engine name\n"
                    "!draw - Show draw policy\n"
                    "!name - Show bot name and version\n"
                    "!ping - Show ping latency\n"
                    "!eval - Show last evaluation\n"
                    "!printeval - Print eval periodically\n"
                    "!pv - Show principal variation (analysis)\n"
                    "!takeback - Show takeback info\n"
                    "!joke - Get a chess joke\n"
                    "!tip - Get a chess tip\n"
                    "!quote - Get a chess quote\n"
                    "!fact - Get a chess fact\n"
                    "!goodluck - Wish good luck\n"
                    "!bye - Say goodbye\n"
                    "!opening - Learn about a random chess opening\n"
                    "!history - Get a historical chess fact\n"
                    "!move - Get a random legal chess move\n"
                    "!challenge - Get info on how to challenge the bot\n"
                    "!rules - Get a basic chess rule\n"
                    "!strategy - Get a chess strategy tip"
                )
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, help_msg)
            case 'joke':
                jokes = [
                    "Why did the chess player bring a pencil to the game? In case they needed to draw!",
                    "What do you call a knight who always gets lost? The wandering knight!",
                    "Why did the pawn get promoted? Because it worked hard!",
                    "Why don't chess players ever get bored? Because they're always making moves!",
                    "Why did the king go to the dentist? To get his crown checked!",
                    "Why did the computer play chess? To avoid a check-up!",
                    "What did the bishop say to the pawn? Diagonally speaking, we're not related.",
                    "Why do chess players never get sunburned? Because they always have a good defense!"
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(jokes))
            case 'tip':
                tips = [
                    "Control the center early in the game.",
                    "Don't move the same piece multiple times in the opening.",
                    "Castle early to protect your king.",
                    "Watch out for forks and pins!",
                    "Develop all your pieces before launching an attack.",
                    "Don't rush pawn moves unless necessary.",
                    "Trade pieces when ahead in material.",
                    "Always check for checks, captures, and threats on every move.",
                    "Connect your rooks for better coordination.",
                    "Think ahead! Try to plan two moves in advance."
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(tips))
            case 'quote':
                quotes = [
                    "\"When you see a good move, look for a better one.\" – Emanuel Lasker",
                    "\"Chess is the struggle against the error.\" – Johannes Zukertort",
                    "\"The beauty of a move lies not in its appearance but in the thought behind it.\" – Aaron Nimzowitsch",
                    "\"Chess holds its master in its own bonds, shackling the mind and brain so that the inner freedom of the very strongest must suffer.\" – Albert Einstein",
                    "\"Even a poor plan is better than no plan at all.\" – Mikhail Chigorin",
                    "\"The blunders are all there on the board, waiting to be made.\" – Savielly Tartakower",
                    "\"You may learn much more from a game you lose than from a game you win.\" – Jose Capablanca",
                    "\"Chess is life in miniature.\" – Garry Kasparov"
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(quotes))
            case 'fact':
                facts = [
                    "The longest chess game theoretically possible is 5,949 moves.",
                    "The word 'Checkmate' comes from the Persian phrase 'Shah Mat', meaning 'the King is dead'.",
                    "There are more possible chess games than atoms in the observable universe.",
                    "The first official World Chess Champion was Wilhelm Steinitz.",
                    "Chess was invented in India around the 6th century.",
                    "The shortest chess game ever played ended after only two moves: 1. f3 e5 2. g4 Qh4#",
                    "Magnus Carlsen became the youngest chess Grandmaster at age 13.",
                    "The longest recorded chess game in history lasted over 20 hours."
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(facts))
            case 'goodluck':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, "Good luck! May the best player win!")
            case 'bye':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, "Goodbye! Thanks for playing!")
            case 'opening':
                openings = [
                    "Ruy Lopez: 1. e4 e5 2. Nf3 Nc6 3. Bb5",
                    "King's Indian Defense: 1. d4 Nf6 2. c4 g6 3. Nc3 Bg7",
                    "Sicilian Defense: 1. e4 c5",
                    "French Defense: 1. e4 e6",
                    "Queen's Gambit: 1. d4 d5 2. c4",
                    "Italian Game: 1. e4 e5 2. Nf3 Nc6 3. Bc4",
                    "Caro-Kann Defense: 1. e4 c6",
                    "English Opening: 1. c4",
                    "Scandinavian Defense: 1. e4 d5"
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, "Random Opening: " + random.choice(openings))
            case 'history':
                history = [
                    "Chess originated in northern India in the 6th century as Chaturanga.",
                    "The first official World Chess Championship was held in 1886.",
                    "Bobby Fischer became the first American World Chess Champion in 1972.",
                    "The famous 'Immortal Game' was played in 1851 between Adolf Anderssen and Lionel Kieseritzky.",
                    "In 1997, IBM's Deep Blue became the first computer to defeat a reigning world champion, Garry Kasparov, in a match."
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(history))
            case 'move':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, "Try developing a knight or controlling the center with a pawn!")
            case 'challenge':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, "To challenge me, send a direct challenge on Lichess or join a public game where I am playing.")
            case 'rules':
                rules = [
                    "The king moves one square in any direction.",
                    "Pawns move forward one square, but capture diagonally.",
                    "Castling is a special move to protect your king and connect your rooks.",
                    "When a pawn reaches the last rank, it gets promoted to another piece.",
                    "Knights move in an L-shape: two squares in one direction, one in the other.",
                    "You win by checkmating your opponent's king!"
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(rules))
            case 'strategy':
                strategies = [
                    "Control the center and use your pieces efficiently.",
                    "Don't rush! Look for threats and double attacks.",
                    "Coordinate your pieces for attack and defense.",
                    "Try to keep your pawn structure solid.",
                    "Don't be afraid to trade pieces if it benefits your position."
                ]
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, random.choice(strategies))

    async def _send_last_message(self, room: str) -> None:
        last_message = self.lichess_game.last_message.replace('Engine', 'Evaluation')
        last_message = ' '.join(last_message.split())

        if room == 'spectator':
            last_message = self._append_pv(last_message)

        await self.api.send_chat_message(self.game_info.id_, room, last_message)

    async def _send_takeback_message(self, room: str, takeback_count: int, max_takebacks: int) -> None:
        if not max_takebacks:
            message = f'{self.username} does not accept takebacks.'
        else:
            message = (f'{self.username} accepts up to {max_takebacks} takeback(s). '
                       f'{self.opponent_username} used {takeback_count} so far.')

        await self.api.send_chat_message(self.game_info.id_, room, message)

    def _get_cpu(self) -> str:
        cpu = ''
        if os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', encoding='utf-8') as cpuinfo:
                while line := cpuinfo.readline():
                    if line.startswith('model name'):
                        cpu = line.split(': ')[1]
                        cpu = cpu.replace('(R)', '')
                        cpu = cpu.replace('(TM)', '')

                        if len(cpu.split()) > 1:
                            return cpu

        if processor := platform.processor():
            cpu = processor.split()[0]
            cpu = cpu.replace('GenuineIntel', 'Intel')

        cores = psutil.cpu_count(logical=False)
        threads = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().max / 1000

        return f'{cpu} {cores}c/{threads}t @ {cpu_freq:.2f}GHz'

    def _get_ram(self) -> str:
        mem_bytes = psutil.virtual_memory().total
        mem_gib = mem_bytes / (1024.**3)

        return f'{mem_gib:.1f} GiB'

    def _get_draw_message(self, config: Config) -> str:
        too_low_rating = (config.offer_draw.min_rating is not None and
                          self.lichess_game.engine.opponent.rating is not None and
                          self.lichess_game.engine.opponent.rating < config.offer_draw.min_rating)
        no_draw_against_humans = (not self.lichess_game.engine.opponent.is_engine and
                                  not config.offer_draw.against_humans)
        if not config.offer_draw.enabled or too_low_rating or no_draw_against_humans:
            return f'{self.username} will neither accept nor offer draws.'

        max_score = config.offer_draw.score / 100

        return (f'{self.username} offers draw at move {config.offer_draw.min_game_length} or later '
                f'if the eval is within +{max_score:.2f} to -{max_score:.2f} for the last '
                f'{config.offer_draw.consecutive_moves} moves.')

    def _get_name_message(self, version: str) -> str:
        return (f'{self.username} running {self.lichess_game.engine.name} (BotLi {version})')

    def _format_message(self, message: str | None) -> str | None:
        if not message:
            return

        mapping = defaultdict(str, {'opponent': self.opponent_username, 'me': self.username,
                                    'engine': self.lichess_game.engine.name, 'cpu': self.cpu_message,
                                    'ram': self.ram_message})
        return message.format_map(mapping)

    def _append_pv(self, initial_message: str = '') -> str:
        if len(self.lichess_game.last_pv) < 2:
            return initial_message

        if initial_message:
            initial_message += ' '

        if self.lichess_game.is_our_turn:
            board = self.lichess_game.board.copy(stack=1)
            board.pop()
        else:
            board = self.lichess_game.board.copy(stack=False)

        if board.turn:
            initial_message += 'PV:'
        else:
            initial_message += f'PV: {board.fullmove_number}...'

        final_message = initial_message
        for move in self.lichess_game.last_pv[1:]:
            if board.turn:
                initial_message += f' {board.fullmove_number}.'
            initial_message += f' {board.san(move)}'
            if len(initial_message) > 140:
                break
            board.push(move)
            final_message = initial_message

        return final_message
