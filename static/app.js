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
let cardScale = 1;
let textScale = 1;
let handOverlap = 0;
let soundEnabled = false;
let prevYourTurn = false;
let handSnapshot = [];

// ---- WebSocket ----
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    const savedId = localStorage.getItem("mishmish-player-id");
    if (savedId) {
      send({ type: "hello", saved_player_id: savedId });
    }
  };

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
      localStorage.setItem("mishmish-player-id", playerId);
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
      isCreator = serverState.is_creator;
      inGame = true;
      if (serverState.your_turn && !prevYourTurn) playTurnSound();
      prevYourTurn = serverState.your_turn;
      if (serverState.status === "ended") {
        resetStaged();
        showView("ended");
        renderEnded();
      } else if (serverState.status === "playing") {
        syncStaged();
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
    `<div class="waiting-player-chip">${escHtml(p.name)}${p.is_bot ? " \uD83E\uDD16" : ""}</div>`
  ).join("");
  const btnStart = document.getElementById("btn-start");
  btnStart.style.display = isCreator ? "inline-block" : "none";
  const btnAddBot = document.getElementById("btn-add-bot");
  btnAddBot.style.display = isCreator ? "inline-block" : "none";
}

function startGame() {
  send({ type: "start_game" });
}

function addBot() {
  send({ type: "add_bot" });
}

// ---- Game ----
function resetStaged() {
  if (!serverState) return;
  stagedHand = serverState.your_hand.map(c => ({ ...c }));
  stagedTable = serverState.table.map(meld => meld.map(c => ({ ...c })));
  sortTableRuns();
}

function syncStaged() {
  if (!serverState) return;
  // Table is always updated from server
  stagedTable = serverState.table.map(meld => meld.map(c => ({ ...c })));
  // Hand preserves the player's custom ordering
  stagedHand = syncHandOrder(stagedHand, serverState.your_hand);
  sortTableRuns();
  // Snapshot hand order at start of each server sync so resetTurn can restore it
  handSnapshot = stagedHand.map(c => ({ ...c }));
}

function syncHandOrder(currentHand, newServerHand) {
  const newCount = {};
  newServerHand.forEach(c => {
    const k = c.rank + c.suit;
    newCount[k] = (newCount[k] || 0) + 1;
  });
  // Keep cards from the current ordered hand that still exist
  const usedCount = {};
  const preserved = currentHand.filter(c => {
    const k = c.rank + c.suit;
    usedCount[k] = (usedCount[k] || 0) + 1;
    return usedCount[k] <= (newCount[k] || 0);
  });
  // Append any new cards (e.g. drawn by opponent doesn't apply here, but handles edge cases)
  const preservedCount = {};
  preserved.forEach(c => {
    const k = c.rank + c.suit;
    preservedCount[k] = (preservedCount[k] || 0) + 1;
  });
  const addedCount = {};
  const newCards = [];
  newServerHand.forEach(c => {
    const k = c.rank + c.suit;
    addedCount[k] = (addedCount[k] || 0) + 1;
    if (addedCount[k] > (preservedCount[k] || 0)) {
      newCards.push({ ...c });
    }
  });
  return [...preserved, ...newCards];
}

function renderGame() {
  if (!serverState) return;

  // Players bar
  const bar = document.getElementById("players-bar");
  bar.innerHTML = serverState.players.map(p =>
    `<div class="player-chip ${p.is_current ? "current-player" : ""}">
      ${escHtml(p.name)}${p.is_bot ? " \uD83E\uDD16" : ""} (${p.hand_size})
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
  const canReorder = serverState.status === "playing";

  // Render table
  renderTable(canAct);

  // Render hand
  renderHand(canAct, canReorder);

  // Buttons
  const hasStaged = canAct && stagedHand.length < serverState.your_hand.length;
  document.getElementById("btn-draw").disabled = !canAct || hasStaged;
  document.getElementById("btn-confirm").disabled = !canAct;
  document.getElementById("btn-reset").disabled = !canAct;
  document.getElementById("btn-sort-hand").disabled = !canReorder;

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
    if (canAct) {
      const slot = document.createElement("div");
      slot.className = "card-drop-slot";
      meldEl.appendChild(slot);
    }
    area.appendChild(meldEl);
  });
}

function renderHand(canAct, canReorder) {
  const area = document.getElementById("hand-area");
  area.innerHTML = "";
  if (canReorder) {
    area.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; });
    area.addEventListener("drop", onDropHandArea);
  }

  stagedHand.forEach((card, cardIdx) => {
    // Cards are draggable if the player can act (play to table) or just reorder
    const cardEl = makeCardEl(card, canAct || canReorder, { from: "hand", cardIdx });
    if (canReorder) {
      cardEl.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        cardEl.classList.add("hand-drag-over");
      });
      cardEl.addEventListener("dragleave", () => cardEl.classList.remove("hand-drag-over"));
      cardEl.addEventListener("drop", (e) => onDropHandCard(e, cardIdx));
    }
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
  e.dataTransfer.setData("text/plain", JSON.stringify(sourceData));
  // Use a semi-transparent clone as the drag image
  const ghost = e.target.cloneNode(true);
  ghost.style.opacity = "0.45";
  ghost.style.position = "fixed";
  ghost.style.top = "-1000px";
  document.body.appendChild(ghost);
  e.dataTransfer.setDragImage(ghost, ghost.offsetWidth / 2, ghost.offsetHeight / 2);
  setTimeout(() => document.body.removeChild(ghost), 0);
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
  sortTableRuns();
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
  sortTableRuns();
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

// ---- Run sorting ----
const RANK_ORDER = ['2','3','4','5','6','7','8','9','10','J','Q','K','A'];

function isRunMeld(cards) {
  if (cards.length < 2) return false;
  const suit = cards[0].suit;
  return cards.every(c => c.suit === suit);
}

function sortRunMeld(cards) {
  const indices = cards.map(c => RANK_ORDER.indexOf(c.rank));
  const sorted = [...cards].sort((a, b) =>
    RANK_ORDER.indexOf(a.rank) - RANK_ORDER.indexOf(b.rank)
  );
  // Check if it's a normal consecutive run
  const si = sorted.map(c => RANK_ORDER.indexOf(c.rank));
  if (si[si.length - 1] - si[0] === si.length - 1) return sorted;
  // Wraparound: find the largest gap in the sorted sequence (including wrap gap)
  let maxGap = 0, maxGapPos = 0;
  for (let i = 0; i < si.length - 1; i++) {
    const gap = si[i + 1] - si[i];
    if (gap > maxGap) { maxGap = gap; maxGapPos = i + 1; }
  }
  const wrapGap = RANK_ORDER.length - si[si.length - 1] + si[0];
  if (wrapGap > maxGap) return sorted; // no rotation needed
  // Rotate: cards from maxGapPos onward come first
  return [...sorted.slice(maxGapPos), ...sorted.slice(0, maxGapPos)];
}

function sortTableRuns() {
  stagedTable = stagedTable.map(meld =>
    isRunMeld(meld) ? sortRunMeld(meld) : meld
  );
}

function sortHand() {
  const SUIT_ORDER = ['S', 'H', 'D', 'C'];
  stagedHand.sort((a, b) => {
    const rankDiff = RANK_ORDER.indexOf(a.rank) - RANK_ORDER.indexOf(b.rank);
    if (rankDiff !== 0) return rankDiff;
    return SUIT_ORDER.indexOf(a.suit) - SUIT_ORDER.indexOf(b.suit);
  });
  renderGame();
}

// ---- Hand reordering ----
function onDropHandCard(e, targetIdx) {
  e.preventDefault();
  e.stopPropagation();
  document.querySelectorAll(".hand-drag-over").forEach(el => el.classList.remove("hand-drag-over"));
  if (!dragSource) return;

  if (dragSource.from === "table") {
    showError("Cards cannot be returned to hand");
    dragSource = null;
    return;
  }

  const sourceIdx = dragSource.cardIdx;
  dragSource = null;
  if (sourceIdx === targetIdx) return;

  const [card] = stagedHand.splice(sourceIdx, 1);
  const adjustedTarget = sourceIdx < targetIdx ? targetIdx - 1 : targetIdx;
  stagedHand.splice(adjustedTarget, 0, card);
  renderGame();
}

function onDropHandArea(e) {
  e.preventDefault();
  document.querySelectorAll(".hand-drag-over").forEach(el => el.classList.remove("hand-drag-over"));
  if (!dragSource) return;

  if (dragSource.from === "table") {
    showError("Cards cannot be returned to hand");
    dragSource = null;
    return;
  }

  const sourceIdx = dragSource.cardIdx;
  dragSource = null;
  const [card] = stagedHand.splice(sourceIdx, 1);
  stagedHand.push(card);
  renderGame();
}

// ---- Display settings ----
function setCardSize(scale) {
  cardScale = parseFloat(scale);
  document.documentElement.style.setProperty("--card-scale", cardScale);
  document.documentElement.style.setProperty("--card-font-scale", cardScale * textScale);
  localStorage.setItem("mishmish-card-scale", cardScale);
}

function setTextSize(scale) {
  textScale = parseFloat(scale);
  document.documentElement.style.setProperty("--card-text-scale", textScale);
  document.documentElement.style.setProperty("--card-font-scale", cardScale * textScale);
  localStorage.setItem("mishmish-text-scale", textScale);
}

function setHandOverlap(px) {
  handOverlap = parseInt(px, 10);
  // px is 0 or negative; CSS margin-left applies the overlap
  document.documentElement.style.setProperty("--hand-overlap", handOverlap + "px");
  localStorage.setItem("mishmish-hand-overlap", handOverlap);
}

function toggleSound(enabled) {
  soundEnabled = enabled;
  localStorage.setItem("mishmish-sound", enabled ? "1" : "0");
}

function playTurnSound() {
  if (!soundEnabled) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch (e) { /* AudioContext not available */ }
}

// ---- Actions ----
function drawCard() {
  send({ type: "draw_card" });
}

function confirmTurn() {
  send({ type: "play_turn", table: stagedTable });
}

function syncState() {
  if (ws) ws.close();
}

function resetTurn() {
  if (!serverState) return;
  stagedHand = handSnapshot.map(c => ({ ...c }));
  stagedTable = serverState.table.map(meld => meld.map(c => ({ ...c })));
  sortTableRuns();
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
  localStorage.removeItem("mishmish-player-id");
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
(function initSettings() {
  const cardSave = localStorage.getItem("mishmish-card-scale");
  if (cardSave) {
    const el = document.getElementById("card-size-slider");
    if (el) el.value = cardSave;
    setCardSize(cardSave);
  }
  const textSave = localStorage.getItem("mishmish-text-scale");
  if (textSave) {
    const el = document.getElementById("text-size-slider");
    if (el) el.value = textSave;
    setTextSize(textSave);
  }
  const overlapSave = localStorage.getItem("mishmish-hand-overlap");
  if (overlapSave) {
    const el = document.getElementById("overlap-slider");
    if (el) el.value = overlapSave;
    setHandOverlap(overlapSave);
  }
  const soundSave = localStorage.getItem("mishmish-sound");
  if (soundSave === "1") {
    soundEnabled = true;
    const el = document.getElementById("sound-toggle");
    if (el) el.checked = true;
  }
})();

connect();
