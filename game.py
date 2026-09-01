"""
협곡의 배신자 — 코어 게임 로직 (MVP+)
추가: 오브젝트(뽑을 때 즉시 발동) / 챔피언 능력(6종, 확장 가능) / 매수(제안·강제)
"""
import random

DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
OPP = [2, 3, 0, 1]
ROWS = 5
START = (2, 0)
NEXUS_COL = 8
NEXUS_CELLS = [(1, NEXUS_COL), (2, NEXUS_COL), (3, NEXUS_COL)]
MIN_COL, MAX_COL = 1, NEXUS_COL - 1
ROLE_RATIO = {4: (3, 1), 5: (3, 2), 6: (4, 2), 7: (4, 3)}
HAND_SIZE = 5

# 구현된 챔피언 (계속 추가 가능)
CHAMPS = {
    "그웬":   {"kind": "passive", "desc": "턴 시작 시 자신의 CC 1개 자동 정화"},
    "알리스타": {"kind": "passive", "desc": "스턴에 면역"},
    "아칼리":  {"kind": "passive", "desc": "스턴 상태에서도 길을 놓을 수 있음"},
    "리븐":   {"kind": "active", "target": "none",  "desc": "이번 턴 길 1장을 추가로 놓는다"},
    "코르키":  {"kind": "active", "target": "pos",   "desc": "카드 없이 무료 갱킹 1회"},
    "직스":   {"kind": "active", "target": "nexus", "desc": "넥서스 후보 1장을 공개한다"},
}


def rot180(edges):
    return [edges[2], edges[3], edges[0], edges[1]]


def _build_deck():
    shapes = [
        ([1, 1, 1, 1], 1, 4), ([1, 1, 1, 0], 1, 3), ([0, 1, 1, 1], 1, 3),
        ([1, 0, 1, 1], 1, 3), ([1, 1, 0, 1], 1, 3), ([1, 0, 1, 0], 1, 5),
        ([0, 1, 0, 1], 1, 5), ([1, 1, 0, 0], 1, 4), ([0, 1, 1, 0], 1, 4),
        ([0, 0, 1, 1], 1, 4), ([1, 0, 0, 1], 1, 4),
        ([1, 0, 1, 0], 0, 2), ([0, 1, 0, 1], 0, 2), ([1, 1, 0, 0], 0, 1), ([0, 0, 1, 1], 0, 1),
    ]
    deck = []
    for edges, conn, cnt in shapes:
        for _ in range(cnt):
            deck.append({"type": "path", "edges": list(edges), "conn": conn})
    for a, cnt in [("stun", 6), ("heal", 4), ("gank", 4), ("ward", 4)]:
        for _ in range(cnt):
            deck.append({"type": "action", "action": a})
    # 오브젝트(뽑을 때 즉시 발동)
    for o, cnt in [("cleanse", 2), ("bonus", 2), ("herald", 2)]:
        for _ in range(cnt):
            deck.append({"type": "object", "obj": o})
    random.shuffle(deck)
    return deck


class Game:
    def __init__(self, players):
        n = len(players)
        if n not in ROLE_RATIO:
            raise ValueError("4~7인만 지원합니다.")
        nm, ns = ROLE_RATIO[n]
        roles = ["소환사"] * nm + ["스파이"] * ns
        random.shuffle(roles)
        names = list(CHAMPS)
        champs = random.sample(names, n) if n <= len(names) else random.choices(names, k=n)

        self.deck = _build_deck()
        self.board = {START: {"kind": "start", "edges": [1, 1, 1, 1], "conn": 1}}
        real = random.randrange(3)
        for i, cell in enumerate(NEXUS_CELLS):
            self.board[cell] = {"kind": "nexus", "revealed": False, "real": (i == real)}

        self.players = []
        for p, role, ch in zip(players, roles, champs):
            self.players.append({
                "id": p["id"], "name": p["name"], "role": role, "champ": ch,
                "hand": [], "blocked": False, "ward_seen": {}, "connected": True,
                "champ_used": False, "double": False, "converted": False,
            })
        self.turn = 0
        self.phase = "진행"
        self.winner = None
        self.pending_bribe = None
        self.force_used = False
        self.log = ["게임 시작! 각자 역할과 챔피언을 확인하세요."]
        for pl in self.players:
            self._draw(pl, HAND_SIZE)

    # ---------- 연결/좌표 ----------
    def _in_bounds(self, r, c):
        return 0 <= r < ROWS and 0 <= c <= NEXUS_COL

    def _reachable(self):
        seen = {START}
        stack = [START]
        while stack:
            r, c = stack.pop()
            tile = self.board.get((r, c))
            if not tile:
                continue
            if tile["kind"] != "start" and tile.get("conn", 0) != 1:
                continue
            if tile["kind"] == "nexus":
                continue
            for d, (dr, dc) in enumerate(DIRS):
                if tile.get("edges", [0, 0, 0, 0])[d] != 1:
                    continue
                nr, nc = r + dr, c + dc
                nb = self.board.get((nr, nc))
                if not nb or nb["kind"] == "nexus":
                    continue
                if nb.get("edges", [0, 0, 0, 0])[OPP[d]] != 1:
                    continue
                if (nr, nc) not in seen:
                    seen.add((nr, nc))
                    stack.append((nr, nc))
        return seen

    def can_place(self, edges, conn, pos):
        r, c = pos
        if not self._in_bounds(r, c) or not (MIN_COL <= c <= MAX_COL):
            return "보드 범위를 벗어났습니다."
        if (r, c) in self.board:
            return "이미 카드가 있습니다."
        reachable = self._reachable()
        placed_neighbors = 0
        connects = False
        for d, (dr, dc) in enumerate(DIRS):
            nr, nc = r + dr, c + dc
            nb = self.board.get((nr, nc))
            if not nb:
                continue
            if nb["kind"] in ("start", "path"):
                placed_neighbors += 1
                if edges[d] != nb["edges"][OPP[d]]:
                    return "인접한 길과 통로가 맞지 않습니다."
                if edges[d] == 1 and nb["edges"][OPP[d]] == 1 and (nr, nc) in reachable:
                    connects = True
        if placed_neighbors == 0:
            return "기존 길에 이어서 놓아야 합니다."
        if not connects:
            return "본진에서 이어진 통로에 연결되지 않습니다."
        return ""

    def _check_nexus(self):
        reachable = self._reachable()
        for i, cell in enumerate(NEXUS_CELLS):
            nx = self.board[cell]
            if nx["revealed"]:
                continue
            nr, nc = cell
            for d, (dr, dc) in enumerate(DIRS):
                pr, pc = nr - dr, nc - dc
                nb = self.board.get((pr, pc))
                if nb and nb["kind"] in ("start", "path") and (pr, pc) in reachable and nb["edges"][d] == 1:
                    self._reveal_nexus(i)
                    break

    def _reveal_nexus(self, i):
        nx = self.board[NEXUS_CELLS[i]]
        if nx["revealed"]:
            return
        nx["revealed"] = True
        self.log.append(f"넥서스 후보 {i+1} 공개 — {'진짜!' if nx['real'] else '가짜(억제기)'}")
        if nx["real"]:
            self.phase = "종료"
            self.winner = "스파이" if False else "소환사"
            self.log.append("소환사 승리! 진짜 넥서스 연결.")

    # ---------- 드로우/오브젝트 ----------
    def _draw(self, pl, count=1):
        drawn = 0
        while self.deck and drawn < count:
            card = self.deck.pop()
            if card["type"] == "object":
                count += self._resolve_object(pl, card["obj"])
                continue
            pl["hand"].append(card)
            drawn += 1

    def _resolve_object(self, pl, obj):
        if obj == "cleanse":
            pl["blocked"] = False
            self.log.append(f"🌊 바다 드래곤 — {pl['name']} 정화")
            return 0
        if obj == "bonus":
            self.log.append(f"🔥 바람 드래곤 — {pl['name']} 카드 보충(+1)")
            return 1
        if obj == "herald":
            paths = [pos for pos, t in self.board.items() if t["kind"] == "path"]
            if paths:
                victim = random.choice(paths)
                del self.board[victim]
                self.log.append(f"👁 협곡의 전령 — 길 {victim} 붕괴")
            return 0
        return 0

    # ---------- 턴 ----------
    def cur(self):
        return self.players[self.turn]

    def _advance(self):
        if self.phase != "진행":
            return
        if not self.deck and all(len(p["hand"]) == 0 for p in self.players):
            self.phase = "종료"
            self.winner = "스파이"
            self.log.append("덱 소진 — 스파이 승리! 넥서스를 지켜냈다.")
            return
        self.turn = (self.turn + 1) % len(self.players)
        nxt = self.players[self.turn]
        if nxt["champ"] == "그웬" and nxt["blocked"]:
            nxt["blocked"] = False
            self.log.append(f"🌫 {nxt['name']}(그웬) 안개로 CC 자동 정화")

    def _find(self, pid):
        for p in self.players:
            if p["id"] == pid:
                return p
        return None

    def action(self, pid, kind, payload):
        if self.phase != "진행":
            return False, "게임이 끝났습니다."
        pl = self.cur()
        if pl["id"] != pid:
            return False, "당신의 턴이 아닙니다."

        if kind == "place":
            idx, pos, rot = payload["hand"], tuple(payload["pos"]), payload.get("rot", 0)
            if pl["blocked"] and pl["champ"] != "아칼리":
                return False, "스턴 상태 — 길을 놓을 수 없습니다."
            if not (0 <= idx < len(pl["hand"])):
                return False, "잘못된 카드."
            card = pl["hand"][idx]
            if card["type"] != "path":
                return False, "길 카드가 아닙니다."
            edges = rot180(card["edges"]) if rot else list(card["edges"])
            why = self.can_place(edges, card["conn"], pos)
            if why:
                return False, why
            self.board[pos] = {"kind": "path", "edges": edges, "conn": card["conn"]}
            pl["hand"].pop(idx)
            self.log.append(f"{pl['name']} 길 배치 {pos}")
            self._check_nexus()
            self._draw(pl)
            if pl.get("double"):
                pl["double"] = False
                self.log.append(f"⚔️ {pl['name']}(리븐) 추가 배치 가능")
                return True, ""   # 턴 유지
            self._advance()
            return True, ""

        if kind == "pass":
            idx = payload.get("hand")
            if idx is not None and 0 <= idx < len(pl["hand"]):
                pl["hand"].pop(idx)
            self.log.append(f"{pl['name']} 패스")
            self._draw(pl)
            self._advance()
            return True, ""

        if kind == "action":
            idx = payload["hand"]
            if not (0 <= idx < len(pl["hand"])):
                return False, "잘못된 카드."
            card = pl["hand"][idx]
            if card["type"] != "action":
                return False, "액션 카드가 아닙니다."
            a = card["action"]

            if a in ("stun", "heal"):
                t = self._find(payload.get("target"))
                if not t:
                    return False, "대상을 찾을 수 없습니다."
                if a == "stun":
                    if t["champ"] == "알리스타":
                        return False, "알리스타는 스턴에 면역입니다."
                    if t["blocked"]:
                        return False, "이미 스턴 상태입니다."
                    t["blocked"] = True
                    self.log.append(f"{pl['name']} → {t['name']} 스턴")
                else:
                    if not t["blocked"]:
                        return False, "정화할 CC가 없습니다."
                    t["blocked"] = False
                    self.log.append(f"{pl['name']} → {t['name']} 정화")
            elif a == "gank":
                pos = tuple(payload["pos"])
                if self.board.get(pos, {}).get("kind") != "path":
                    return False, "부술 길이 없습니다."
                del self.board[pos]
                self.log.append(f"{pl['name']} 갱킹 {pos}")
            elif a == "ward":
                ni = payload.get("nexus")
                if ni is None or not (0 <= ni < 3):
                    return False, "넥서스 후보를 지정하세요."
                pl["ward_seen"][ni] = self.board[NEXUS_CELLS[ni]]["real"]
                self.log.append(f"{pl['name']} 와드 정찰")
            else:
                return False, "알 수 없는 액션."

            pl["hand"].pop(idx)
            self._draw(pl)
            self._advance()
            return True, ""

        return False, "알 수 없는 행동."

    # ---------- 챔피언 능력 ----------
    def use_ability(self, pid, payload):
        if self.phase != "진행":
            return False, "게임이 끝났습니다."
        pl = self.cur()
        if pl["id"] != pid:
            return False, "당신의 턴에만 사용할 수 있습니다."
        ch = pl["champ"]
        info = CHAMPS.get(ch, {})
        if info.get("kind") != "active":
            return False, "발동형 능력이 아닙니다."
        if pl["champ_used"]:
            return False, "이미 사용했습니다."

        if ch == "리븐":
            pl["double"] = True
            pl["champ_used"] = True
            self.log.append(f"⚔️ {pl['name']}(리븐) 파멸의 검 — 추가 배치 준비")
            return True, ""     # 턴 유지, 길 배치로 이어짐
        if ch == "코르키":
            pos = tuple(payload.get("pos", []))
            if self.board.get(pos, {}).get("kind") != "path":
                return False, "부술 길을 지정하세요."
            del self.board[pos]
            pl["champ_used"] = True
            self.log.append(f"🚀 {pl['name']}(코르키) 특수 배송 — 길 {pos} 폭격")
            self._draw(pl)
            self._advance()
            return True, ""
        if ch == "직스":
            ni = payload.get("nexus")
            if ni is None or not (0 <= ni < 3):
                return False, "넥서스 후보를 지정하세요."
            pl["champ_used"] = True
            self.log.append(f"💣 {pl['name']}(직스) 넥서스 후보 {ni+1} 강제 공개")
            self._reveal_nexus(ni)
            if self.phase == "진행":
                self._draw(pl)
                self._advance()
            return True, ""
        return False, "미구현 능력."

    # ---------- 매수 ----------
    def bribe(self, pid, payload):
        if self.phase != "진행":
            return False, "게임이 끝났습니다.", None
        pl = self.cur()
        if pl["id"] != pid:
            return False, "당신의 턴이 아닙니다.", None
        if pl["role"] != "스파이":
            return False, "스파이만 매수할 수 있습니다.", None
        mode = payload.get("mode")
        t = self._find(payload.get("target"))
        if not t or t["role"] == "스파이":
            return False, "매수할 소환사를 지정하세요.", None

        if mode == "force":
            if self.force_used:
                return False, "강제 매수는 게임당 1회뿐입니다.", None
            self.force_used = True
            t["role"] = "스파이"
            t["converted"] = True
            self.log.append(f"⛓ {t['name']}가 세뇌되어 전향했다! (정체 노출)")
            self._advance()
            return True, "", None
        if mode == "offer":
            self.pending_bribe = {"to": t["id"], "from": pl["name"]}
            self.log.append(f"{pl['name']}가 은밀히 누군가에게 제안을 보냈다…")
            self._advance()
            return True, "", t["id"]     # 서버가 대상에게 알림
        return False, "알 수 없는 매수 방식.", None

    def bribe_response(self, pid, accept):
        pb = self.pending_bribe
        if not pb or pb["to"] != pid:
            return False, "받은 제안이 없습니다."
        self.pending_bribe = None
        if accept:
            t = self._find(pid)
            t["role"] = "스파이"
            self.log.append("어둠의 거래가 성사되었다… (비밀)")
        else:
            self.log.append("제안이 거절되었다.")
        return True, ""

    # ---------- 뷰 ----------
    def public_board(self):
        out = {}
        for (r, c), t in self.board.items():
            if t["kind"] == "nexus":
                out[f"{r},{c}"] = {"kind": "nexus", "revealed": t["revealed"],
                                   "real": (t["real"] if t["revealed"] else None)}
            else:
                out[f"{r},{c}"] = {"kind": t["kind"], "edges": t["edges"], "conn": t["conn"]}
        return out

    def view_for(self, pid):
        me = self._find(pid)
        my_turn = bool(self.players and self.players[self.turn]["id"] == pid and self.phase == "진행")
        champ = me["champ"] if me else None
        info = CHAMPS.get(champ, {})
        goal = ("본진에서 진짜 넥서스까지 길을 이으면 승리합니다."
                if (me and me["role"] == "소환사")
                else "덱이 소진될 때까지 진짜 넥서스 연결을 막으면 승리합니다.")
        return {
            "phase": self.phase, "winner": self.winner, "turn": self.turn,
            "turnName": self.players[self.turn]["name"] if self.players else "",
            "board": self.public_board(),
            "players": [{"id": p["id"], "name": p["name"], "blocked": p["blocked"],
                         "hand": len(p["hand"]), "connected": p["connected"],
                         "converted": p["converted"], "champ": p["champ"]} for p in self.players],
            "log": self.log[-14:],
            "me": None if not me else {
                "id": me["id"], "role": me["role"], "blocked": me["blocked"],
                "hand": me["hand"], "wardSeen": me["ward_seen"], "myTurn": my_turn,
                "champ": champ, "champKind": info.get("kind"), "champDesc": info.get("desc", ""),
                "champTarget": info.get("target"), "abilityReady": (info.get("kind") == "active" and not me["champ_used"]),
                "isSpy": me["role"] == "스파이", "forceUsed": self.force_used, "goal": goal,
                "bribeOffer": (self.pending_bribe["from"] if self.pending_bribe and self.pending_bribe["to"] == pid else None),
            },
            "meta": {"rows": ROWS, "cols": NEXUS_COL + 1, "start": list(START),
                     "nexus": [list(c) for c in NEXUS_CELLS]},
        }


if __name__ == "__main__":
    g = Game([{"id": str(i), "name": f"P{i}"} for i in range(4)])
    print("역할/챔피언:", [(p["name"], p["role"], p["champ"]) for p in g.players])
    print("덱 남은:", len(g.deck), "/ P0 손패:", len(g.players[0]["hand"]))
    v = g.view_for("0")
    print("me.champ:", v["me"]["champ"], "abilityReady:", v["me"]["abilityReady"])
    print("남 역할 노출 안 됨:", all("role" not in pp for pp in v["players"]))
