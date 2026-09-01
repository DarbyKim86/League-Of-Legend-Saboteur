"""
협곡의 배신자 — 실시간 웹게임 서버 (Flask-SocketIO)
- 방 생성/입장 → 방장이 시작 → 실시간 턴 진행.
- 히든롤: 매 갱신마다 각 소켓에 '그 사람이 볼 수 있는 뷰'만 전송.
- 화면(HTML/JS)은 이 파일에 내장(A안).
실행: python game_server.py  (로컬)  /  배포: gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 game_server:app
"""
import os
import random
import string
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, join_room, emit

from game import Game, ROLE_RATIO

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

# 방 저장 (메모리)
ROOMS = {}   # code -> {'host':sid, 'players':[{sid,id,name}], 'game':Game|None}


def new_code():
    while True:
        c = "".join(random.choices(string.ascii_uppercase, k=4))
        if c not in ROOMS:
            return c


def room_of(sid):
    for code, r in ROOMS.items():
        for p in r["players"]:
            if p["sid"] == sid:
                return code, r, p
    return None, None, None


def push(code):
    """방 전원에게 각자의 뷰를 개별 전송."""
    r = ROOMS.get(code)
    if not r:
        return
    if r["game"]:
        for p in r["players"]:
            socketio.emit("state", r["game"].view_for(p["id"]), to=p["sid"])
    else:
        lobby = {"phase": "대기", "code": code, "host": r["host_id"],
                 "players": [{"id": p["id"], "name": p["name"]} for p in r["players"]]}
        socketio.emit("lobby", lobby, to=code)


# ---------- Socket 이벤트 ----------
@socketio.on("create_room")
def on_create(data):
    name = (data.get("name") or "익명").strip()[:12]
    code = new_code()
    pid = request.sid
    ROOMS[code] = {"host": request.sid, "host_id": pid,
                   "players": [{"sid": request.sid, "id": pid, "name": name}], "game": None}
    join_room(code)
    emit("joined", {"code": code, "id": pid})
    push(code)


@socketio.on("join_room")
def on_join(data):
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "익명").strip()[:12]
    r = ROOMS.get(code)
    if not r:
        emit("err", {"msg": "방을 찾을 수 없습니다."}); return
    if r["game"]:
        emit("err", {"msg": "이미 시작된 방입니다."}); return
    if len(r["players"]) >= 7:
        emit("err", {"msg": "정원(7명)이 찼습니다."}); return
    pid = request.sid
    r["players"].append({"sid": request.sid, "id": pid, "name": name})
    join_room(code)
    emit("joined", {"code": code, "id": pid})
    push(code)


@socketio.on("start_game")
def on_start(data):
    code, r, p = room_of(request.sid)
    if not r or r["host"] != request.sid:
        emit("err", {"msg": "방장만 시작할 수 있습니다."}); return
    n = len(r["players"])
    if n not in ROLE_RATIO:
        emit("err", {"msg": "4~7명이어야 시작할 수 있습니다."}); return
    r["game"] = Game([{"id": p["id"], "name": p["name"]} for p in r["players"]])
    push(code)


@socketio.on("act")
def on_act(data):
    code, r, p = room_of(request.sid)
    if not r or not r["game"]:
        return
    ok, msg = r["game"].action(p["id"], data.get("kind"), data.get("payload", {}))
    if not ok:
        emit("err", {"msg": msg})
    push(code)


@socketio.on("ability")
def on_ability(data):
    code, r, p = room_of(request.sid)
    if not r or not r["game"]:
        return
    ok, msg = r["game"].use_ability(p["id"], data.get("payload", {}))
    if not ok:
        emit("err", {"msg": msg})
    push(code)


@socketio.on("bribe")
def on_bribe(data):
    code, r, p = room_of(request.sid)
    if not r or not r["game"]:
        return
    ok, msg, notify = r["game"].bribe(p["id"], data.get("payload", {}))
    if not ok:
        emit("err", {"msg": msg})
    push(code)


@socketio.on("bribe_response")
def on_bribe_response(data):
    code, r, p = room_of(request.sid)
    if not r or not r["game"]:
        return
    r["game"].bribe_response(p["id"], bool(data.get("accept")))
    push(code)


@socketio.on("disconnect")
def on_disc():
    code, r, p = room_of(request.sid)
    if not r:
        return
    if r["game"]:
        # 진행 중 이탈: 표시만(간단 MVP — 자리 유지)
        for pp in r["game"].players:
            if pp["id"] == p["id"]:
                pp["connected"] = False
        push(code)
    else:
        r["players"] = [x for x in r["players"] if x["sid"] != request.sid]
        if not r["players"]:
            ROOMS.pop(code, None)
        else:
            if r["host"] == request.sid:
                r["host"] = r["players"][0]["sid"]
                r["host_id"] = r["players"][0]["id"]
            push(code)


@app.route("/")
def index():
    return render_template_string(PAGE)


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>협곡의 배신자</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<style>
  :root{
    --rift:#050e1c; --rift2:#08182b; --panel:#0c2136; --panel2:#102b45; --line:#1c3d59;
    --gold:#c8aa6e; --gold2:#f0e6d2; --bronze:#785a28; --teal:#0ac8b9; --teald:#0397ab;
    --blue:#3c89c9; --red:#c6443e; --text:#cfe3f0; --muted:#6f92ab; --cell:52px;
  }
  *{box-sizing:border-box}
  body{margin:0;color:var(--text);font-family:Inter,system-ui,sans-serif;padding:16px 14px 40px;
    max-width:820px;margin:0 auto;min-height:100vh;
    background:
      radial-gradient(1100px 500px at 50% -8%, rgba(10,200,185,.10), transparent 60%),
      radial-gradient(800px 400px at 50% 110%, rgba(200,170,110,.08), transparent 60%),
      var(--rift);}
  h1{font-family:Cinzel,serif;font-weight:700;font-size:22px;letter-spacing:.04em;margin:2px 0 16px;
    color:var(--gold2);text-align:center;text-shadow:0 0 18px rgba(200,170,110,.35)}
  h1 .sub{display:block;font-family:Inter;font-weight:500;font-size:12px;letter-spacing:.28em;
    color:var(--teal);margin-top:5px}
  button{font-family:Inter;background:linear-gradient(180deg,#d8bd82,#b7975a);color:#20160a;border:0;
    border-radius:7px;padding:10px 16px;font-weight:600;cursor:pointer;transition:filter .12s}
  button:hover{filter:brightness(1.08)} button:disabled{filter:grayscale(.6) brightness(.7);cursor:default}
  button.sec{background:transparent;border:1px solid var(--line);color:var(--text)}
  button.sec:hover{border-color:var(--gold);background:var(--panel2)}
  input{background:#071726;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:10px 11px;font-size:15px}
  input:focus{outline:none;border-color:var(--teald)}
  .panel{background:linear-gradient(180deg,rgba(16,43,69,.75),rgba(10,26,44,.85));
    border:1px solid var(--line);border-radius:12px;padding:15px;margin-bottom:12px;
    box-shadow:inset 0 1px 0 rgba(120,90,40,.18)}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--muted)} .err{color:var(--red);min-height:18px;font-size:13px}
  .hdr{font-family:Cinzel,serif;font-size:14px;letter-spacing:.06em;color:var(--gold);margin-bottom:9px}

  /* 역할 크레스트 */
  .crest{display:inline-flex;align-items:center;gap:7px;font-weight:700}
  .crest.m{color:var(--blue)} .crest.s{color:var(--red)}
  .crest .dot{width:9px;height:9px;border-radius:50%;box-shadow:0 0 8px currentColor;background:currentColor}
  .turnpill{font-family:Cinzel,serif;font-size:13px;color:var(--gold2)}

  /* 보드 */
  #boardwrap{display:flex;justify-content:center;margin:10px -6px}
  #board{display:grid;gap:4px;padding:12px;border-radius:14px;
    background:
      radial-gradient(120% 120% at 12% 0%, rgba(60,137,201,.10), transparent 55%),
      radial-gradient(120% 120% at 88% 100%, rgba(198,68,62,.10), transparent 55%),
      linear-gradient(180deg,#0a1c30,#07131f);
    border:1px solid var(--line);box-shadow:0 8px 30px rgba(0,0,0,.4), inset 0 0 0 1px rgba(120,90,40,.10);
    overflow:auto;max-width:100%}
  .cell{width:var(--cell);height:var(--cell);border-radius:8px;background:#0a1a2b;
    border:1px solid #12283d;position:relative;color:var(--bronze);transition:transform .1s}
  .cell.empty{cursor:pointer;background:repeating-linear-gradient(45deg,#0a1a2b,#0a1a2b 6px,#0b1e30 6px,#0b1e30 12px)}
  .cell.empty:hover{outline:2px solid var(--gold);outline-offset:-1px}
  .cell.path{background:#0b2033;border-color:#1a3247}
  .cell.path.lit{color:var(--gold2);border-color:var(--gold);box-shadow:0 0 12px rgba(200,170,110,.28)}
  .cell.start{background:radial-gradient(circle at 50% 50%,rgba(60,137,201,.30),#0a1a2b);border-color:var(--blue)}
  .cell.nexus{cursor:default}
  .cell.gankable{cursor:crosshair} .cell.gankable:hover{outline:2px solid var(--red);outline-offset:-1px}
  .cell.wardable{cursor:help} .cell.wardable:hover{outline:2px solid var(--blue);outline-offset:-1px}
  .cell svg{display:block}
  .placed{animation:pop .28s ease-out}
  @keyframes pop{0%{transform:scale(.7);opacity:.3}70%{transform:scale(1.08)}100%{transform:scale(1)}}
  .revealed{animation:flash .6s ease-out}
  @keyframes flash{0%{filter:brightness(2.4)}100%{filter:brightness(1)}}
  .wardmark{position:absolute;top:2px;right:3px;font-size:10px;line-height:1}

  /* 손패 */
  .hand{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}
  .hc{width:56px;height:56px;border-radius:9px;background:#0b2033;border:1px solid #1a3247;
    position:relative;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:2px;transition:transform .1s,border-color .1s}
  .hc:hover{transform:translateY(-3px)} .hc.sel{border-color:var(--gold);box-shadow:0 0 12px rgba(200,170,110,.4)}
  .hc .lab{font-size:10px;color:var(--muted)}
  .hc.act .ic{font-size:20px;line-height:1}
  .hc.stun{border-color:rgba(198,68,62,.5)} .hc.heal{border-color:rgba(10,200,185,.5)}
  .hc.gank{border-color:rgba(200,170,110,.5)} .hc.ward{border-color:rgba(60,137,201,.5)}
  #handbox.myturn{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold), 0 0 24px rgba(200,170,110,.18)}
  .hint{font-size:12.5px;color:var(--teal);margin-top:9px;min-height:16px}

  /* 플레이어 */
  .pl{display:flex;justify-content:space-between;align-items:center;padding:8px 11px;border:1px solid var(--line);
    border-radius:9px;margin-bottom:6px;background:rgba(10,26,44,.5);cursor:default}
  .pl.turn{border-color:var(--gold);background:var(--panel2);box-shadow:inset 3px 0 0 var(--gold)}
  .pl.me{outline:1px solid rgba(60,137,201,.35)}
  .pl.clickable{cursor:pointer} .pl.clickable:hover{border-color:var(--teal)}
  .badge{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
  .badge.stun{color:var(--red);border-color:rgba(198,68,62,.6)}
  .badge.gold{color:var(--gold2);border-color:var(--gold)}

  .log{font-size:12px;color:var(--muted);line-height:1.65;max-height:130px;overflow:auto}
  .log b{color:var(--text)}

  /* 승리 */
  .verdict{text-align:center;padding:22px 14px}
  .verdict .big{font-family:Cinzel,serif;font-size:30px;letter-spacing:.03em;
    text-shadow:0 0 26px currentColor;animation:rise .6s ease-out}
  .verdict .big.m{color:var(--blue)} .verdict .big.s{color:var(--red)}
  .verdict .me{margin-top:8px;font-size:14px}
  @keyframes rise{0%{opacity:0;transform:translateY(14px) scale(.9)}100%{opacity:1;transform:none}}

  .code-badge{font-family:Cinzel,serif;letter-spacing:5px;color:var(--gold2);font-size:22px;
    background:#071726;border:1px solid var(--gold);border-radius:8px;padding:4px 14px}
  .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:10px;justify-content:center}
  .legend span{display:inline-flex;align-items:center;gap:4px}
  .sw{width:11px;height:11px;border-radius:3px;display:inline-block}

  /* 시작 공개 연출 */
  .reveal-ov{position:fixed;inset:0;z-index:100;display:none;align-items:center;justify-content:center;padding:20px;
    background:radial-gradient(circle at 50% 38%, rgba(3,10,20,.72), rgba(2,6,14,.94))}
  .reveal-card{max-width:390px;width:100%;text-align:center;border:1px solid var(--line);border-radius:16px;
    padding:32px 26px;background:linear-gradient(180deg,rgba(16,43,69,.94),rgba(7,17,31,.97));animation:revcard .5s ease-out both}
  .reveal-ov.m .reveal-card{box-shadow:0 0 60px rgba(60,137,201,.35);border-color:var(--blue)}
  .reveal-ov.s .reveal-card{box-shadow:0 0 60px rgba(198,68,62,.35);border-color:var(--red)}
  .reveal-emblem{font-size:48px;animation:revpop .6s .1s both}
  .reveal-kicker{letter-spacing:.26em;font-size:12px;color:var(--muted);margin-top:8px;animation:revup .5s .28s both}
  .reveal-role{font-family:Cinzel,serif;font-weight:700;font-size:46px;letter-spacing:.04em;margin:2px 0 12px;animation:revup .5s .38s both}
  .reveal-ov.m .reveal-role{color:var(--blue);text-shadow:0 0 32px rgba(60,137,201,.65)}
  .reveal-ov.s .reveal-role{color:var(--red);text-shadow:0 0 32px rgba(198,68,62,.65)}
  .reveal-goal{color:var(--text);font-size:14px;line-height:1.65;animation:revup .5s .48s both}
  .reveal-champ{margin:18px 0 24px;padding:13px;border-radius:11px;background:rgba(200,170,110,.09);
    border:1px solid rgba(200,170,110,.28);animation:revup .5s .58s both}
  .reveal-champ b{display:block;font-family:Cinzel,serif;color:var(--gold2);font-size:19px;margin-bottom:4px}
  .reveal-champ span{font-size:12.5px;color:var(--muted)}
  .reveal-card button{width:100%;animation:revup .5s .68s both}
  @keyframes revcard{0%{opacity:0;transform:scale(.94)}100%{opacity:1;transform:none}}
  @keyframes revpop{0%{opacity:0;transform:scale(.3) rotate(-12deg)}70%{transform:scale(1.15)}100%{opacity:1;transform:none}}
  @keyframes revup{0%{opacity:0;transform:translateY(12px)}100%{opacity:1;transform:none}}
</style></head><body>
<h1>협곡의 배신자<span class="sub">RIFT · TRAITORS OF THE RIFT</span></h1>

<div id="home" class="panel">
  <div class="hdr">소환사 등록</div>
  <div class="row"><input id="name" placeholder="닉네임" maxlength="12" style="flex:1"></div>
  <div class="row" style="margin-top:10px">
    <button onclick="createRoom()">방 만들기</button>
    <input id="code" placeholder="방 코드" maxlength="4" style="width:110px;text-transform:uppercase;letter-spacing:3px">
    <button class="sec" onclick="joinRoom()">입장</button>
  </div>
  <div class="err" id="homeErr"></div>
</div>

<div id="lobby" class="panel" style="display:none">
  <div class="row" style="justify-content:space-between;align-items:center">
    <div>방 코드 <span class="code-badge" id="lcode"></span></div>
    <button id="startBtn" onclick="startGame()" style="display:none">게임 시작</button>
  </div>
  <div id="lplayers" style="margin-top:14px"></div>
  <div class="muted" style="font-size:12px;margin-top:10px">소환사 4~7명이 모이면 방장이 시작할 수 있습니다.</div>
</div>

<div id="game" style="display:none">
  <div class="panel" id="topbar"></div>
  <div id="boardwrap"><div id="board"></div></div>
  <div class="legend" id="legend"></div>
  <div class="err" id="gErr"></div>
  <div class="panel" id="handbox">
    <div class="row" style="justify-content:space-between">
      <div class="hdr" style="margin:0">내 손패</div>
      <div class="row">
        <button class="sec" id="rotBtn" onclick="rotate()">회전 ↻</button>
        <button class="sec" onclick="doPass()">패스</button>
      </div>
    </div>
    <div class="hand" id="hand"></div>
    <div class="hint" id="hint"></div>
  </div>
  <div class="panel"><div class="hdr">소환사</div><div id="players"></div></div>
  <div class="panel"><div class="hdr">전투 기록</div><div class="log" id="log"></div></div>
</div>

<div id="reveal" class="reveal-ov"></div>

<script>
const s = io();
let MYID=null, CODE=null, ST=null, sel=null, rot=0, mode=null, revealed=false, prevKeys=new Set(), prevNexus={};
const $=q=>document.querySelector(q);
const esc=t=>(t==null?'':(''+t)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function createRoom(){ s.emit('create_room',{name:$('#name').value}); }
function joinRoom(){ s.emit('join_room',{name:$('#name').value, code:$('#code').value}); }
function startGame(){ s.emit('start_game',{}); }

s.on('err', d=>{ $('#homeErr').textContent=d.msg; const g=$('#gErr'); if(g){g.textContent=d.msg; setTimeout(()=>{g.textContent='';},2600);} });
s.on('joined', d=>{ MYID=d.id; CODE=d.code; });
s.on('lobby', d=>renderLobby(d));
s.on('state', d=>{ ST=d; renderGame(d); });

function show(id){ ['home','lobby','game'].forEach(x=>$('#'+x).style.display = x===id?'':'none'); }

// ---- SVG 타일 ----
function tileSVG(edges,conn){
  const A={0:[22,0,12,30],1:[26,22,30,12],2:[22,26,12,30],3:[0,22,30,12]};
  let arms='';
  for(let i=0;i<4;i++) if(edges[i]){const m=A[i];arms+=`<rect x="${m[0]}" y="${m[1]}" width="${m[2]}" height="${m[3]}" rx="3" fill="currentColor"/>`;}
  const hub = conn
    ? '<circle cx="28" cy="28" r="10" fill="currentColor"/>'
    : '<rect x="18" y="18" width="20" height="20" rx="4" fill="#2a0f0f"/><path d="M23 23 L33 33 M33 23 L23 33" stroke="#c6443e" stroke-width="2.6" stroke-linecap="round"/>';
  return `<svg viewBox="0 0 56 56" width="100%" height="100%">${arms}${hub}</svg>`;
}
function startSVG(){
  return `<svg viewBox="0 0 56 56" width="100%" height="100%">
    <circle cx="28" cy="28" r="15" fill="none" stroke="#3c89c9" stroke-width="2.4"/>
    <circle cx="28" cy="28" r="8" fill="#3c89c9" opacity="0.55"/>
    <circle cx="28" cy="28" r="3" fill="#cfe3f0"/></svg>`;
}
function crystalSVG(state){
  const c = state==='real'?'#f0e6d2':state==='fake'?'#c6443e':'#0ac8b9';
  const fillOp = state==='hidden'?0.22:0.6;
  const sym = state==='real'?'★':state==='fake'?'✕':'?';
  return `<svg viewBox="0 0 56 56" width="100%" height="100%">
    <polygon points="28,5 47,28 28,51 9,28" fill="none" stroke="${c}" stroke-width="2.4"/>
    <polygon points="28,14 39,28 28,42 17,28" fill="${c}" opacity="${fillOp}"/>
    <text x="28" y="34" text-anchor="middle" font-size="16" font-family="Cinzel,serif" fill="${c}">${sym}</text></svg>`;
}

function clientReachable(d){
  const DIRS=[[-1,0],[0,1],[1,0],[0,-1]], OPP=[2,3,0,1];
  const sc=d.meta.start; const seen=new Set([sc.join(',')]); const stack=[sc];
  while(stack.length){
    const [r,c]=stack.pop(); const t=d.board[r+','+c]; if(!t) continue;
    if(t.kind!=='start' && t.conn!==1) continue;
    if(t.kind==='nexus') continue;
    const e=t.edges||[0,0,0,0];
    for(let i=0;i<4;i++){ if(!e[i]) continue;
      const nr=r+DIRS[i][0], nc=c+DIRS[i][1], nb=d.board[nr+','+nc];
      if(!nb||nb.kind==='nexus') continue;
      if((nb.edges||[0,0,0,0])[OPP[i]]!==1) continue;
      const k=nr+','+nc; if(!seen.has(k)){seen.add(k);stack.push([nr,nc]);}
    }
  }
  return seen;
}

function renderLobby(d){
  show('lobby'); $('#lcode').textContent=d.code;
  $('#lplayers').innerHTML=d.players.map(p=>`<div class="pl"><span>${esc(p.name)}${p.id===d.host?' <span class="badge gold">방장</span>':''}${p.id===MYID?' <span class="muted">(나)</span>':''}</span></div>`).join('');
  const isHost=d.host===MYID, ok=d.players.length>=4&&d.players.length<=7;
  const b=$('#startBtn'); b.style.display=isHost?'':'none'; b.disabled=!ok;
  b.textContent = ok?'게임 시작':`4~7명 필요 (${d.players.length})`;
}

function renderGame(d){
  show('game');
  const me=d.me;
  if(!revealed && me && d.phase==='진행'){ revealed=true; showReveal(me); }
  if(d.phase==='종료'){ renderEnd(d); return; }
  const crest = me ? `<span class="crest ${me.role==='스파이'?'s':'m'}"><span class="dot"></span>${me.role}</span>` : '';
  const yourTurn = me&&me.myTurn;
  let ctrls='';
  if(me && yourTurn){
    if(me.abilityReady) ctrls+=`<button class="sec" onclick="useAbility()">능력 · ${esc(me.champ)}</button>`;
    if(me.isSpy){
      ctrls+=`<button class="sec" onclick="startBribe('offer')">매수 제안</button>`;
      ctrls+=`<button class="sec" onclick="startBribe('force')" ${me.forceUsed?'disabled':''}>강제 매수</button>`;
    }
  }
  const champLine = me?`<div class="muted" style="font-size:12px;margin-top:7px;cursor:pointer" onclick="if(ST&&ST.me)showReveal(ST.me)" title="다시 보기">챔피언 <b style="color:var(--gold2)">${esc(me.champ)}</b> — ${esc(me.champDesc)}<br>목표 · ${esc(me.goal)} <span style="color:var(--teal)">ⓘ</span></div>`:'';
  let bribeBox='';
  if(me && me.bribeOffer){
    bribeBox=`<div class="panel" style="margin:11px 0 0;border-color:var(--red)">
      <b style="color:var(--red)">⛓ 은밀한 제안이 도착했다</b>
      <div class="muted" style="font-size:12px;margin:5px 0 9px">누군가 당신을 스파이로 끌어들이려 합니다. 수락하면 스파이 승리 조건으로 전환됩니다.</div>
      <div class="row"><button onclick="respondBribe(true)">수락</button><button class="sec" onclick="respondBribe(false)">거절</button></div></div>`;
  }
  $('#topbar').innerHTML = `<div class="row" style="justify-content:space-between">
    <div>내 역할 ${crest}</div>
    <div class="turnpill">${yourTurn?'⚔️ 당신의 차례':'⏳ '+esc(d.turnName)+' 차례'}</div></div>
    ${champLine}${ctrls?`<div class="row" style="margin-top:9px">${ctrls}</div>`:''}${bribeBox}`;

  renderBoard(d);
  $('#legend').innerHTML = `
    <span><span class="sw" style="background:var(--gold2)"></span>연결된 길</span>
    <span><span class="sw" style="background:var(--bronze)"></span>끊긴 길</span>
    <span><span class="sw" style="background:#2a0f0f;border:1px solid var(--red)"></span>막힌 길</span>
    <span><span class="sw" style="background:var(--teal)"></span>넥서스(?)</span>`;

  const hb=$('#handbox'); hb.classList.toggle('myturn', !!yourTurn);
  if(me){
    const ACT={stun:['⚡','스턴'],heal:['✚','정화'],gank:['💥','갱킹'],ward:['👁','와드']};
    $('#hand').innerHTML = me.hand.map((c,i)=>{
      if(c.type==='path')
        return `<div class="hc ${sel===i?'sel':''}" onclick="pickHand(${i})">${tileSVG(c.edges,c.conn)}</div>`;
      const a=ACT[c.action];
      return `<div class="hc act ${c.action} ${sel===i?'sel':''}" onclick="pickHand(${i})"><span class="ic">${a[0]}</span><span class="lab">${a[1]}</span></div>`;
    }).join('') || '<span class="muted">손패 없음</span>';
    updateHint();
  }

  $('#players').innerHTML = d.players.map((p,i)=>{
    const isTgt = (canTargetPlayer() || mode==='bribe_offer' || mode==='bribe_force') && p.id!==MYID;
    return `<div class="pl ${i===d.turn?'turn':''} ${p.id===MYID?'me':''} ${isTgt?'clickable':''}" data-i="${i}">
      <span>${esc(p.name)}${p.id===MYID?' <span class="muted">(나)</span>':''} ${p.converted?'<span class="badge stun">전향</span>':''} ${p.connected?'':'<span class="badge">이탈</span>'}</span>
      <span>${p.blocked?'<span class="badge stun">스턴</span> ':''}<span class="badge">손 ${p.hand}</span></span></div>`;
  }).join('');
  $('#log').innerHTML = d.log.map(l=>`<div>· ${esc(l)}</div>`).reverse().join('');
}

function renderBoard(d){
  const {rows,cols}=d.meta;
  const reach=clientReachable(d);
  const bd=$('#board'); bd.style.gridTemplateColumns=`repeat(${cols}, var(--cell))`;
  const nowKeys=new Set(Object.keys(d.board).filter(k=>{const t=d.board[k];return t.kind==='path';}));
  let html='';
  for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){
    const key=r+','+c, t=d.board[key]; let cls='cell', inner='', extra='';
    const canGank=selIsAction('gank')||mode==='ab_pos', canWard=selIsAction('ward')||mode==='ab_nexus';
    if(!t){ cls+=' empty'; }
    else if(t.kind==='start'){ cls+=' start'; inner=startSVG(); }
    else if(t.kind==='nexus'){
      cls+=' nexus';
      let state = t.revealed ? (t.real?'real':'fake') : 'hidden';
      inner=crystalSVG(state);
      if(canWard && !t.revealed) cls+=' wardable';
      const ni=nexusIndex(d,r,c);
      if(!t.revealed && d.me && d.me.wardSeen && (ni in d.me.wardSeen)){
        const real=d.me.wardSeen[ni];
        extra=`<span class="wardmark">${real?'⭐':'🚫'}</span>`;
      }
      if(t.revealed && !prevNexus[key]) cls+=' revealed';
    } else {
      cls+=' path'+(reach.has(key)?' lit':'');
      inner=tileSVG(t.edges,t.conn);
      if(!prevKeys.has(key)) cls+=' placed';
      if(canGank) cls+=' gankable';
    }
    html+=`<div class="${cls}" onclick="clickCell(${r},${c})">${inner}${extra}</div>`;
  }
  bd.innerHTML=html;
  prevKeys=nowKeys;
  prevNexus={}; for(const k in d.board){ if(d.board[k].kind==='nexus'&&d.board[k].revealed) prevNexus[k]=1; }
}

function renderEnd(d){
  const me=d.me;
  const cls=d.winner==='스파이'?'s':'m';
  const mine = me? (me.role===d.winner?'승리했습니다 🎉':'패배했습니다') : '';
  $('#topbar').innerHTML = `<div class="verdict">
    <div class="big ${cls}">${d.winner} 승리</div>
    <div class="me muted">${me?('당신은 '+me.role+' — '+mine):''}</div></div>`;
  renderBoard(d);
  $('#legend').innerHTML='';
  $('#handbox').classList.remove('myturn');
  $('#hand').innerHTML=''; $('#hint').textContent='새 게임을 하려면 페이지를 새로고침하세요.';
  $('#players').innerHTML = d.players.map((p,i)=>`<div class="pl"><span>${esc(p.name)}${p.id===MYID?' (나)':''}</span></div>`).join('');
  $('#log').innerHTML = d.log.map(l=>`<div>· ${esc(l)}</div>`).reverse().join('');
}

function nexusIndex(d,r,c){ return d.meta.nexus.findIndex(n=>n[0]===r&&n[1]===c); }
function selCard(){ return (ST&&ST.me&&sel!==null)?ST.me.hand[sel]:null; }
function selIsAction(a){ const c=selCard(); return c&&c.type==='action'&&c.action===a; }
function canTargetPlayer(){ const c=selCard(); return c&&c.type==='action'&&(c.action==='stun'||c.action==='heal'); }

function pickHand(i){ if(!ST||!ST.me||!ST.me.myTurn) return; sel=(sel===i?null:i); rot=0; mode=null; renderGame(ST); }
function rotate(){ if(sel===null) return; rot^=1; updateHint(); }

function useAbility(){
  const me=ST&&ST.me; if(!me||!me.myTurn||!me.abilityReady) return;
  sel=null;
  if(me.champTarget==='none'){ s.emit('ability',{payload:{}}); mode=null; }
  else { mode = me.champTarget==='pos'?'ab_pos':(me.champTarget==='nexus'?'ab_nexus':'ab_player'); renderGame(ST); }
}
function startBribe(m){ const me=ST&&ST.me; if(!me||!me.myTurn||!me.isSpy) return; sel=null; mode='bribe_'+m; renderGame(ST); }
function respondBribe(a){ s.emit('bribe_response',{accept:a}); }

function showReveal(me){
  const spy = me.role==='스파이';
  const ov=$('#reveal'); ov.className='reveal-ov '+(spy?'s':'m');
  ov.innerHTML=`<div class="reveal-card">
    <div class="reveal-emblem">${spy?'🗡️':'🛡️'}</div>
    <div class="reveal-kicker">${spy?'매수된 배신자':'협곡의 수호자'}</div>
    <div class="reveal-role">${esc(me.role)}</div>
    <div class="reveal-goal">${esc(me.goal)}</div>
    <div class="reveal-champ"><b>${esc(me.champ)}</b><span>${esc(me.champDesc)}</span></div>
    <button onclick="closeReveal()">협곡으로 입장 ⚔️</button></div>`;
  ov.style.display='flex';
}
function closeReveal(){ $('#reveal').style.display='none'; }

function updateHint(){
  const me=ST&&ST.me; const h=$('#hint'); if(!me){h.textContent='';return;}
  if(!me.myTurn){ h.textContent='다른 소환사의 차례입니다.'; return; }
  if(mode==='ab_pos'){ h.textContent='능력 · 부술 길을 누르세요.'; return; }
  if(mode==='ab_nexus'){ h.textContent='능력 · 공개할 넥서스(?)를 누르세요.'; return; }
  if(mode==='bribe_offer'){ h.textContent='매수 제안할 소환사를 목록에서 누르세요.'; return; }
  if(mode==='bribe_force'){ h.textContent='강제 매수(공개 전향)할 소환사를 누르세요.'; return; }
  const c=selCard();
  if(!c){ h.textContent='손패에서 카드를 고르세요.'; return; }
  if(c.type==='path') h.textContent = me.blocked?'스턴 상태 — 길을 놓을 수 없습니다. 정화가 필요합니다.'
    : `빈 칸을 눌러 길을 놓으세요. 회전 상태: ${rot?'180°':'기본'}`;
  else if(c.action==='gank') h.textContent='부술 길(빨강 테두리)을 누르세요.';
  else if(c.action==='ward') h.textContent='정찰할 넥서스(?)를 누르세요.';
  else if(c.action==='stun') h.textContent='스턴할 소환사를 아래 목록에서 누르세요.';
  else if(c.action==='heal') h.textContent='정화할 소환사를 아래 목록에서 누르세요.';
}

function clickCell(r,c){
  const me=ST&&ST.me; if(!me||!me.myTurn) return;
  const t=ST.board[r+','+c];
  if(mode==='ab_pos'){ if(!t||t.kind!=='path') return; s.emit('ability',{payload:{pos:[r,c]}}); mode=null; return; }
  if(mode==='ab_nexus'){ const ni=nexusIndex(ST,r,c); if(ni<0) return; s.emit('ability',{payload:{nexus:ni}}); mode=null; return; }
  if(sel===null) return;
  const card=selCard();
  if(card.type==='path'){ if(t) return; s.emit('act',{kind:'place',payload:{hand:sel,pos:[r,c],rot}}); sel=null; }
  else if(card.action==='gank'){ if(!t||t.kind!=='path') return; s.emit('act',{kind:'action',payload:{hand:sel,pos:[r,c]}}); sel=null; }
  else if(card.action==='ward'){ const ni=nexusIndex(ST,r,c); if(ni<0) return; s.emit('act',{kind:'action',payload:{hand:sel,nexus:ni}}); sel=null; }
}

document.addEventListener('click',e=>{
  const pl=e.target.closest('#players .pl'); if(!pl||!ST||!ST.me||!ST.me.myTurn) return;
  const i=+pl.dataset.i; const tgt=ST.players[i]; if(!tgt||tgt.id===MYID) return;
  if(mode==='bribe_offer'||mode==='bribe_force'){
    s.emit('bribe',{payload:{mode:mode==='bribe_offer'?'offer':'force',target:tgt.id}}); mode=null; return;
  }
  const card=selCard();
  if(card&&card.type==='action'&&(card.action==='stun'||card.action==='heal')){
    s.emit('act',{kind:'action',payload:{hand:sel,target:tgt.id}}); sel=null;
  }
});

function doPass(){ const me=ST&&ST.me; if(!me||!me.myTurn) return; s.emit('act',{kind:'pass',payload:{hand: sel!==null?sel:undefined}}); sel=null; }
</script>
</body></html>
"""

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
