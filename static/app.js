// ---- State ----
let ws = null;
let playerId = null;
let serverState = null;
let stagedHand = [];
let stagedTable = [];
let inGame = false;
let isCreator = false;
let playerName = "";
let dragSource = null;

// ---- WebSocket ----
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    setTimeout(connect, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function handleMessage(msg) {
  switch (msg.type) {
    case "connected":
      playerId = msg.player_id;
      break;

    case "lobby_state":
      if (!inGame) {
        renderLobby(msg.games);
      }
      break;

    case "joined_game":
      inGame = true;
      isCreator = msg.is_creator;
      showView("waiting");
      break;

    case "game_state":
      serverState = msg.state;
      if (serverState.status === "ended") {
        resetStaged();
        showView("ended");
        renderEnded();
      } else if (serverState.status === "playing") {
        resetStaged();
        showView("game");
        renderGame();
      } else {
        // waiting
        renderWaiting();
      }
      break;

    case "error":
      showError(msg.message);
      break;
  }
}

// ---- Views ----
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(`view-${name}`).classList.add("active");
}

// ---- Lobby ----
function renderLobby(games) {
  const list = document.getElementById("game-list");
  if (!games || games.length === 0) {
    list.innerHTML = '<p class="empty-msg">No games available. Create one!</p>';
    return;
  }
  list.innerHTML = games.map(g => `
    <div class="game-item">
      <div class="game-item-info">
        <div class="game-item-players">${escHtml(g.players.join(", "))}</div>
        <div>${g.player_count} player(s) &mdash; ${g.status}</div>
      </div>
      ${g.status === "waiting"
        ? `<button onclick="joinGame('${g.game_id}')">Join</button>`
        : `<span style="color:#6a8f6a;font-size:0.85rem">In progress</span>`
      }
    </div>
  `).join("");
}

function createGame() {
  const name = document.getElementById("player-name").value.trim();
  if (!name) { showError("Enter your name first"); return; }
  playerName = name;
  send({ type: "create_game", name });
}

function joinGame(gameId) {
  const name = document.getElementById("player-name").value.trim();
  if (!name) { showError("Enter your name first"); return; }
  playerName = name;
  send({ type: "join_game", game_id: gameId, name });
}

// ---- Waiting ----
function renderWaiting() {
  if (!serverState) return;
  document.getElementById("waiting-game-id").textContent = `Game ID: ${serverState.game_id}`;
  const pDiv = document.getElementById("waiting-players");
  pDiv.innerHTML = serverState.players.map(p =>
    `<div class="waiting-player-chip">${escHtml(p.name)}</div>`
  ).join("");
  const btnStart = document.getElementById("btn-start");
  btnStart.style.display = isCreator ? "inline-block" : "none";
}

function startGame() {
  send({ type: "start_game" });
}

// ---- Game ----
function resetStaged() {
  if (!serverState) return;
  // Deep copy
  stagedHand = serverState.your_hand.map(c => ({ ...c }));
  stagedTable = serverState.table.map(meld => meld.map(c => ({ ...c })));
}

function renderGame() {
  if (!serverState) return;

  // Players bar
  const bar = document.getElementById("players-bar");
  bar.innerHTML = serverState.players.map(p =>
    `<div class="player-chip ${p.is_current ? "current-player" : ""}">
      ${escHtml(p.name)} (${p.hand_size})
    </div>`
  ).join("");

  // Draw pile
  document.getElementById("draw-pile-count").textContent = serverState.draw_pile_size;

  // Message
  const msgEl = document.getElementById("game-message");
  if (serverState.your_turn) {
    msgEl.textContent = "Your turn!";
  } else {
    msgEl.textContent = `${escHtml(serverState.current_player_name || "")}'s turn`;
  }

  const canAct = serverState.your_turn && serverState.status === "playing";

  // Render table
  renderTable(canAct);

  // Render hand
  renderHand(canAct);

  // Buttons
  document.getElementById("btn-draw").disabled = !canAct;
  document.getElementById("btn-confirm").disabled = !canAct;
  document.getElementById("btn-reset").disabled = !canAct;

  // New meld zone visibility
  document.getElementById("new-meld-zone").style.display = canAct ? "flex" : "none";
}

function renderTable(canAct) {
  const area = document.getElementById("table-area");
  area.innerHTML = "";
  stagedTable.forEach((meld, meldIdx) => {
    const meldEl = document.createElement("div");
    meldEl.className = "meld";
    if (canAct) {
      meldEl.setAttribute("data-meld-idx", meldIdx);
      meldEl.addEventListener("dragover", onDragOver);
      meldEl.addEventListener("dragleave", onDragLeave);
      meldEl.addEventListener("drop", (e) => onDropMeld(e, meldIdx));
    }
    meld.forEach((card, cardIdx) => {
      const cardEl = makeCardEl(card, canAct, { from: "table", meldIdx, cardIdx });
      meldEl.appendChild(cardEl);
    });
    area.appendChild(meldEl);
  });
}

function renderHand(canAct) {
  const area = document.getElementById("hand-area");
  area.innerHTML = "";
  stagedHand.forEach((card, cardIdx) => {
    const cardEl = makeCardEl(card, canAct, { from: "hand", cardIdx });
    area.appendChild(cardEl);
  });
}

// ---- Card element ----
const SUIT_SYMBOLS = { H: "♥", D: "♦", C: "♣", S: "♠" };

function makeCardEl(card, draggable, sourceData) {
  const el = document.createElement("div");
  el.className = "card";
  const isRed = card.suit === "H" || card.suit === "D";
  el.classList.add(isRed ? "red" : "black");

  const sym = SUIT_SYMBOLS[card.suit] || card.suit;

  el.innerHTML = `
    <span class="card-rank-top">${escHtml(card.rank)}</span>
    <span class="card-suit-top">${sym}</span>
    <span class="card-center">${sym}</span>
    <span class="card-rank-bot">${escHtml(card.rank)}</span>
    <span class="card-suit-bot">${sym}</span>
  `;

  if (draggable) {
    el.classList.add("draggable");
    el.setAttribute("draggable", "true");
    el.addEventListener("dragstart", (e) => onDragStart(e, sourceData));
    el.addEventListener("dragend", onDragEnd);
  }

  return el;
}

// ---- Drag & Drop ----
function onDragStart(e, sourceData) {
  dragSource = sourceData;
  e.dataTransfer.effectAllowed = "move";
  // Store a placeholder so the browser has something
  e.dataTransfer.setData("text/plain", JSON.stringify(sourceData));
}

function onDragEnd(e) {
  // Clean up any drag-over highlights
  document.querySelectorAll(".drag-over").forEach(el => el.classList.remove("drag-over"));
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  e.currentTarget.classList.add("drag-over");
}

function onDragLeave(e) {
  e.currentTarget.classList.remove("drag-over");
}

function onDropMeld(e, targetMeldIdx) {
  e.preventDefault();
  e.currentTarget.classList.remove("drag-over");

  if (!dragSource) return;

  // If dropping on the same meld from the same meld, do nothing meaningful
  if (dragSource.from === "table" && dragSource.meldIdx === targetMeldIdx) {
    dragSource = null;
    return;
  }

  // Remove card from source FIRST, then add to target (important for index stability)
  const card = removeCardFromSource(dragSource);
  if (!card) { dragSource = null; return; }

  // After removal, adjust targetMeldIdx if source was a table meld with lower index
  let adjustedTargetIdx = targetMeldIdx;
  if (dragSource.from === "table" && dragSource.meldIdx < targetMeldIdx) {
    // The meld at targetMeldIdx may have shifted after cleanEmptyMelds
    // We'll clean empty melds after adding to handle this
  }

  // Add card to target meld (use adjustedTargetIdx but note cleanEmptyMelds hasn't run yet)
  if (adjustedTargetIdx < stagedTable.length) {
    stagedTable[adjustedTargetIdx].push(card);
  } else {
    // Fallback: new meld
    stagedTable.push([card]);
  }

  cleanEmptyMelds();
  dragSource = null;
  renderGame();
}

function onDropNewMeld(e) {
  e.preventDefault();
  e.currentTarget.classList.remove("drag-over");

  if (!dragSource) return;

  const card = removeCardFromSource(dragSource);
  if (!card) { dragSource = null; return; }

  stagedTable.push([card]);
  cleanEmptyMelds();
  dragSource = null;
  renderGame();
}

function removeCardFromSource(source) {
  if (source.from === "hand") {
    if (source.cardIdx >= stagedHand.length) return null;
    const [card] = stagedHand.splice(source.cardIdx, 1);
    return card;
  } else if (source.from === "table") {
    const meld = stagedTable[source.meldIdx];
    if (!meld || source.cardIdx >= meld.length) return null;
    const [card] = meld.splice(source.cardIdx, 1);
    return card;
  }
  return null;
}

function cleanEmptyMelds() {
  stagedTable = stagedTable.filter(meld => meld.length > 0);
}

// ---- Actions ----
function drawCard() {
  send({ type: "draw_card" });
}

function confirmTurn() {
  send({ type: "play_turn", table: stagedTable });
}

function resetTurn() {
  resetStaged();
  renderGame();
}

// ---- Ended ----
function renderEnded() {
  const msgEl = document.getElementById("ended-message");
  if (serverState && serverState.winner) {
    msgEl.textContent = `${serverState.winner} wins!`;
  } else {
    msgEl.textContent = "It's a draw! The deck ran out.";
  }
}

function backToLobby() {
  inGame = false;
  isCreator = false;
  serverState = null;
  stagedHand = [];
  stagedTable = [];
  showView("lobby");
  send({ type: "lobby_request" }); // server will ignore; lobby state sent on next change
  // Request fresh lobby state by reconnecting or just wait for next broadcast
  // For immediate update, we can ask the server:
  // Actually, we just trust the server to broadcast lobby state when needed.
  // Reload page to cleanly reconnect.
  location.reload();
}

// ---- Error ----
let errorTimer = null;
function showError(msg) {
  const el = document.getElementById("error-msg");
  if (!el) {
    alert(msg);
    return;
  }
  el.textContent = msg;
  el.style.display = "block";
  if (errorTimer) clearTimeout(errorTimer);
  errorTimer = setTimeout(() => {
    el.style.display = "none";
  }, 3000);
}

// ---- Utilities ----
function escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---- Init ----
connect();
