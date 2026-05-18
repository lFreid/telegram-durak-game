"""
Логика карточной игры Дурак (подкидной и переводной)
"""
import random
from enum import Enum
from typing import Optional

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}

class GameType(str, Enum):
    PODKIDNOY = "podkidnoy"
    PEREVODNOJ = "perevodnoj"

class Card:
    def __init__(self, suit: str, rank: str):
        self.suit = suit
        self.rank = rank

    def beats(self, other: "Card", trump: str) -> bool:
        if self.suit == other.suit:
            return RANK_ORDER[self.rank] > RANK_ORDER[other.rank]
        return self.suit == trump

    def to_dict(self):
        return {"suit": self.suit, "rank": self.rank, "str": f"{self.rank}{self.suit}"}

    def __repr__(self):
        return f"{self.rank}{self.suit}"

def make_deck() -> list[Card]:
    deck = [Card(s, r) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck

class GameState(str, Enum):
    WAITING   = "waiting"
    PLAYING   = "playing"
    FINISHED  = "finished"

class DurakGame:
    MAX_PLAYERS = 3

    def __init__(self, game_id: str, game_type: GameType = GameType.PODKIDNOY):
        self.game_id    = game_id
        self.game_type  = game_type
        self.state      = GameState.WAITING
        self.players: list[dict] = []   # [{id, name}]
        self.hands: dict[int, list[Card]] = {}
        self.deck: list[Card] = []
        self.trump: str = ""
        self.trump_card: Optional[Card] = None
        self.table: list[dict] = []     # [{attack: Card, defense: Card|None}]
        self.attacker_idx  = 0
        self.defender_idx  = 1
        self.loser_id: Optional[int] = None   # дурак

    # ── Участники ─────────────────────────────────────────────────────────────
    def add_player(self, user_id: int, name: str) -> bool:
        if len(self.players) >= self.MAX_PLAYERS:
            return False
        if any(p["id"] == user_id for p in self.players):
            return False
        self.players.append({"id": user_id, "name": name})
        return True

    # ── Старт ─────────────────────────────────────────────────────────────────
    def start(self) -> bool:
        if len(self.players) < 2:
            return False
        self.deck = make_deck()
        # Раздача по 6 карт
        for p in self.players:
            self.hands[p["id"]] = [self.deck.pop() for _ in range(6)]
        # Козырь
        self.trump_card = self.deck[-1]
        self.trump = self.trump_card.suit
        self.attacker_idx = 0
        self.defender_idx = 1
        self.state = GameState.PLAYING
        self.table = []
        return True

    # ── Ход атаки ─────────────────────────────────────────────────────────────
    def attack(self, user_id: int, card_str: str) -> dict:
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Игра не идёт"}
        attacker = self.players[self.attacker_idx]
        if attacker["id"] != user_id:
            return {"ok": False, "error": "Не твой ход"}
        card = self._find_card(user_id, card_str)
        if not card:
            return {"ok": False, "error": "Карта не найдена"}
        # Первый ход — любая карта; следующие — только совпадающий ранг
        if self.table and not any(
            p["attack"].rank == card.rank or (p["defense"] and p["defense"].rank == card.rank)
            for p in self.table
        ):
            return {"ok": False, "error": "Нельзя подкинуть такую карту"}
        # Нельзя подкидывать больше карт чем у защитника
        defender = self.players[self.defender_idx]
        if len(self.table) >= len(self.hands[defender["id"]]):
            return {"ok": False, "error": "Слишком много карт для защитника"}
        self.hands[user_id].remove(card)
        self.table.append({"attack": card, "defense": None})
        return {"ok": True}

    # ── Ход защиты ────────────────────────────────────────────────────────────
    def defend(self, user_id: int, attack_idx: int, card_str: str) -> dict:
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Игра не идёт"}
        defender = self.players[self.defender_idx]
        if defender["id"] != user_id:
            return {"ok": False, "error": "Не твой ход защищаться"}
        if attack_idx >= len(self.table):
            return {"ok": False, "error": "Неверный индекс атаки"}
        slot = self.table[attack_idx]
        if slot["defense"] is not None:
            return {"ok": False, "error": "Карта уже отбита"}
        card = self._find_card(user_id, card_str)
        if not card:
            return {"ok": False, "error": "Карта не найдена"}
        if not card.beats(slot["attack"], self.trump):
            return {"ok": False, "error": "Карта не бьёт"}
        self.hands[user_id].remove(card)
        slot["defense"] = card
        return {"ok": True}

    # ── Перевод (только переводной) ───────────────────────────────────────────
    def transfer(self, user_id: int, card_str: str) -> dict:
        if self.game_type != GameType.PEREVODNOJ:
            return {"ok": False, "error": "Перевод только в переводном дураке"}
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Игра не идёт"}
        defender = self.players[self.defender_idx]
        if defender["id"] != user_id:
            return {"ok": False, "error": "Не твой ход"}
        if len(self.table) != 1 or self.table[0]["defense"] is not None:
            return {"ok": False, "error": "Перевод только на первой карте"}
        card = self._find_card(user_id, card_str)
        if not card:
            return {"ok": False, "error": "Карта не найдена"}
        if card.rank != self.table[0]["attack"].rank:
            return {"ok": False, "error": "Ранг должен совпадать"}
        # Следующий игрок теперь защитник
        next_def_idx = (self.defender_idx + 1) % len(self.players)
        if next_def_idx == self.attacker_idx:
            next_def_idx = (next_def_idx + 1) % len(self.players)
        self.hands[user_id].remove(card)
        self.table.append({"attack": card, "defense": None})
        # Атакующий → бывший защитник, защитник → следующий
        self.attacker_idx = self.defender_idx
        self.defender_idx = next_def_idx
        return {"ok": True, "transferred": True}

    # ── Взять карты (защитник сдаётся) ───────────────────────────────────────
    def take(self, user_id: int) -> dict:
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Игра не идёт"}
        defender = self.players[self.defender_idx]
        if defender["id"] != user_id:
            return {"ok": False, "error": "Только защитник берёт карты"}
        for slot in self.table:
            self.hands[user_id].append(slot["attack"])
            if slot["defense"]:
                self.hands[user_id].append(slot["defense"])
        self.table = []
        # Атакующий остаётся, защитник меняется
        self.defender_idx = (self.defender_idx + 1) % len(self.players)
        if self.defender_idx == self.attacker_idx:
            self.defender_idx = (self.defender_idx + 1) % len(self.players)
        self._refill()
        self._check_finish()
        return {"ok": True}

    # ── Завершить ход (все карты отбиты) ─────────────────────────────────────
    def end_turn(self, user_id: int) -> dict:
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Игра не идёт"}
        attacker = self.players[self.attacker_idx]
        if attacker["id"] != user_id:
            return {"ok": False, "error": "Только атакующий завершает ход"}
        if any(slot["defense"] is None for slot in self.table):
            return {"ok": False, "error": "Не все карты отбиты"}
        self.table = []
        self.attacker_idx = self.defender_idx
        self.defender_idx = (self.defender_idx + 1) % len(self.players)
        if self.defender_idx == self.attacker_idx:
            self.defender_idx = (self.defender_idx + 1) % len(self.players)
        self._refill()
        self._check_finish()
        return {"ok": True}

    # ── Добор карт ────────────────────────────────────────────────────────────
    def _refill(self):
        order = [self.attacker_idx]
        idx = (self.attacker_idx + 1) % len(self.players)
        while idx != self.attacker_idx:
            if idx != self.defender_idx:
                order.append(idx)
            idx = (idx + 1) % len(self.players)
        order.append(self.defender_idx)
        for i in order:
            pid = self.players[i]["id"]
            while len(self.hands[pid]) < 6 and self.deck:
                self.hands[pid].append(self.deck.pop())

    # ── Проверка конца игры ───────────────────────────────────────────────────
    def _check_finish(self):
        alive = [p for p in self.players if self.hands[p["id"]]]
        if len(alive) <= 1 and not self.deck:
            self.state = GameState.FINISHED
            if len(alive) == 1:
                self.loser_id = alive[0]["id"]

    # ── Утилиты ───────────────────────────────────────────────────────────────
    def _find_card(self, user_id: int, card_str: str) -> Optional[Card]:
        for c in self.hands.get(user_id, []):
            if f"{c.rank}{c.suit}" == card_str:
                return c
        return None

    def public_state(self, viewer_id: int) -> dict:
        """Состояние игры с точки зрения конкретного игрока"""
        attacker_id = self.players[self.attacker_idx]["id"] if self.players else None
        defender_id = self.players[self.defender_idx]["id"] if len(self.players) > 1 else None
        return {
            "game_id":    self.game_id,
            "game_type":  self.game_type,
            "state":      self.state,
            "trump":      self.trump,
            "trump_card": self.trump_card.to_dict() if self.trump_card else None,
            "deck_count": len(self.deck),
            "players":    [
                {
                    "id":         p["id"],
                    "name":       p["name"],
                    "card_count": len(self.hands.get(p["id"], [])),
                    "is_attacker": p["id"] == attacker_id,
                    "is_defender": p["id"] == defender_id,
                }
                for p in self.players
            ],
            "my_hand":    [c.to_dict() for c in self.hands.get(viewer_id, [])],
            "table":      [
                {
                    "attack":  s["attack"].to_dict(),
                    "defense": s["defense"].to_dict() if s["defense"] else None,
                    "idx":     i,
                }
                for i, s in enumerate(self.table)
            ],
            "attacker_id": attacker_id,
            "defender_id": defender_id,
            "loser_id":    self.loser_id,
            "am_attacker": viewer_id == attacker_id,
            "am_defender": viewer_id == defender_id,
        }
