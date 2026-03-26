"use strict";

// --------- Small helpers ---------
const $ = (id) => document.getElementById(id);
const pcs = new Map(); // peerId -> RTCPeerConnection
const dcs = new Map(); // peerId -> RTCDataChannel
const statuses = new Map(); // peerId -> 'disconnected' | 'connecting' | 'connected'
let peersInChannel = new Set();
let offerLoopOn = true;
let answerLoopOn = false;

function nowTime() {
  return new Date().toLocaleTimeString();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2000);
}
function log(...a) {
  const d = document.createElement("div");
  d.textContent = `[${nowTime()}] ` + a.join(" ");
  $("log").appendChild(d);
  $("log").scrollTop = $("log").scrollHeight;
}
function addMsg(from, msg) {
  const d = document.createElement("div");
  d.textContent = `${from}: ${msg}`;
  $("msgs").appendChild(d);
  $("msgs").scrollTop = $("msgs").scrollHeight;
}
function setBadge() {
  const anyOpen = [...dcs.values()].some((dc) => dc.readyState === "open");
  const b = $("dcBadge");
  b.className = "badge " + (anyOpen ? "ok" : "");
  b.textContent = "DC: " + (anyOpen ? "open" : "closed");
}
function statusDotHTML(state) {
  const cls =
    state === "connected" ? "ok" : state === "connecting" ? "warn" : "";
  return `<span class="status-dot ${cls}"></span>`;
}

// --------- HTTP wrapper ---------
async function api(url, opts = {}) {
  const init = Object.assign({ credentials: "include" }, opts);
  const r = await fetch(url, init);
  if (r.status === 401) {
    location.href = "/login.html";
    throw new Error("unauthorized");
  }
  return r;
}

// --------- Auth ---------
$("logout").onclick = async () => {
  try {
    const r = await fetch("/api/logout", {
      method: "POST",
      credentials: "include",
    });
    if (r.ok) location.href = "/login.html";
    else toast("Logout failed");
  } catch (e) {
    toast("Logout error");
    log("logout error:", e?.message || e);
  }
};

// --------- Identity & Channel ---------
$("btnSubmitInfo").onclick = submitInfo;
$("btnJoin").onclick = joinChannel;
$("btnRefresh").onclick = refreshPeers;
$("btnConnectAll").onclick = connectAll;

async function submitInfo() {
  const peerId = $("me").value.trim();
  if (!peerId) return toast("Set My Peer ID");
  const public_ip = "n/a";
  const private_ip = location.hostname || "n/a";
  try {
    const r = await api(`/api/submit-info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ peerId, public_ip, private_ip }),
    });
    if (!r.ok) return toast("submit-info failed");
    $("whoami").textContent = `You are ${peerId} @ ${private_ip}`;
    log("Registered as", peerId);
    ensureOfferLoopRunning();
    await refreshPeers(); // show something right away
  } catch (e) {
    toast("submit-info error");
    log("submit-info error:", e?.message || e);
  }
}

async function joinChannel() {
  const peerId = $("me").value.trim();
  const chan = $("channel").value.trim();
  if (!peerId || !chan) return toast("Set Peer ID and Channel");
  try {
    const r = await api(`/api/add-list`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: chan, peerId }),
    });
    if (!r.ok) return toast("add-list failed");
    log("Joined channel", chan);
    await refreshPeers();
  } catch (e) {
    toast("add-list error");
    log("add-list error:", e?.message || e);
  }
}

async function refreshPeers() {
  const me = $("me").value.trim();
  const chan = $("channel").value.trim();
  if (!chan) return toast("Set Channel");
  try {
    // NOTE: backend expects x-channel header (not query string)
    const r = await api(`/api/get-list`, {
      method: "GET",
      headers: { "x-channel": chan },
    });
    if (!r.ok) return toast("get-list failed");

    const data = await r.json();
    const box = $("peers");
    box.innerHTML = "";
    peersInChannel = new Set();
    (data.peers || []).forEach((p) => {
      const pid = p.peerId || p.id || "";
      if (!pid || pid === me) return;
      peersInChannel.add(pid);
      const state = statuses.get(pid) || "disconnected";
      const row = document.createElement("div");
      row.className = "peer-line";
      row.innerHTML = `
        <div class="mono">${statusDotHTML(state)}
          <strong>${pid}</strong>
          <span class="muted">· seen ${
            (Math.max(0, Date.now() - (p.lastSeen || 0)) / 1000) | 0
          }s ago</span>
        </div>
        <div class="row">
          <button class="btn" data-pid="${pid}" data-act="offer">
            ${state === "connected" ? "Reconnect" : "Offer"}
          </button>
          <button class="btn danger" data-pid="${pid}" data-act="disconnect">Disconnect</button>
        </div>`;
      box.appendChild(row);
    });
    if (peersInChannel.size === 0)
      box.textContent = "(no other peers in channel yet)";
  } catch (e) {
    log("refreshPeers error:", e?.message || e);
  }
}

async function connectAll() {
  if (peersInChannel.size === 0) return toast("No peers");
  for (const pid of peersInChannel) {
    const st = statuses.get(pid);
    if (st === "connected" || st === "connecting") continue;
    // eslint-disable-next-line no-await-in-loop
    await offerTo(pid);
  }
}

$("peers").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const pid = btn.getAttribute("data-pid");
  const act = btn.getAttribute("data-act");
  if (act === "offer") {
    offerTo(pid);
  } else if (act === "disconnect") {
    disconnectFrom(pid);
  }
});

// --------- WebRTC & signaling ---------
function newPC(peerId) {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  pc.ondatachannel = (ev) => bindDC(peerId, ev.channel);
  pc.onconnectionstatechange = () => {
    log(peerId, "pc:", pc.connectionState);
    if (pc.connectionState === "connected") {
      statuses.set(peerId, "connected");
      refreshPeers();
    }
    if (
      pc.connectionState === "failed" ||
      pc.connectionState === "disconnected"
    ) {
      statuses.set(peerId, "disconnected");
      refreshPeers();
    }
  };
  pc.oniceconnectionstatechange = () =>
    log(peerId, "ice:", pc.iceConnectionState);
  return pc;
}

function bindDC(peerId, dc) {
  dcs.set(peerId, dc);
  dc.onopen = () => {
    log(peerId, "dc open");
    statuses.set(peerId, "connected");
    setBadge();
    refreshPeers();
  };
  dc.onclose = () => {
    log(peerId, "dc close");
    statuses.set(peerId, "disconnected");
    setBadge();
    refreshPeers();
  };
  dc.onmessage = (ev) => addMsg(peerId, String(ev.data));
}

async function completeIce(pc) {
  if (pc.iceGatheringState === "complete") return;
  await new Promise((res) => {
    const chk = () => pc.iceGatheringState === "complete" && res();
    pc.addEventListener("icegatheringstatechange", chk);
    setTimeout(res, 1200);
  });
}

async function offerTo(to) {
  const me = $("me").value.trim();
  if (!me) return toast("Set My Peer ID");
  statuses.set(to, "connecting");
  refreshPeers();

  const pc = newPC(to);
  pcs.set(to, pc);
  const dc = pc.createDataChannel("chat", { ordered: true });
  bindDC(to, dc);

  const off = await pc.createOffer({
    offerToReceiveAudio: false,
    offerToReceiveVideo: false,
  });
  await pc.setLocalDescription(off);
  await completeIce(pc);
  const sdp = pc.localDescription.sdp;

  try {
    const r = await api(`/api/connect-peer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from: me, to, sdp }),
    });
    if (!r.ok) {
      toast("connect-peer failed");
      return;
    }
    log("offer →", to);
    ensureAnswerLoopRunning();
  } catch (e) {
    toast("connect-peer error");
    log("connect-peer error:", e?.message || e);
  }
}

function disconnectFrom(pid) {
  try {
    dcs.get(pid)?.close();
  } catch {}
  try {
    pcs.get(pid)?.close();
  } catch {}
  dcs.delete(pid);
  pcs.delete(pid);
  statuses.set(pid, "disconnected");
  setBadge();
  refreshPeers();
  log("disconnected from", pid);
}

async function offerLoop() {
  while (offerLoopOn) {
    const me = $("me").value.trim();
    if (!me) {
      await sleep(400);
      continue;
    }
    try {
      const r = await api(`/api/connect-peer/get`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peerId: me, wait: true }),
      });
      const data = await r.json();
      if (data && data.sdp && data.from) {
        const from = data.from;
        const ok = confirm(`Incoming connection from ${from}. Accept?`);
        if (ok) {
          const pc = newPC(from);
          pcs.set(from, pc);
          await pc.setRemoteDescription({ type: "offer", sdp: data.sdp });
          const ans = await pc.createAnswer();
          await pc.setLocalDescription(ans);
          await completeIce(pc);
          const sdp = pc.localDescription.sdp;
          await api(`/api/send-peer`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ from: me, to: from, sdp }),
          });
          statuses.set(from, "connecting");
          refreshPeers();
          log("answer →", from);
        } else {
          try {
            await api(`/api/connect-peer/decline`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ peerId: me, from: data.from }),
            });
          } catch {}
          log("declined offer from", data.from);
        }
      }
    } catch (e) {
      log("offerLoop error:", e?.message || e);
    }
    await sleep(60);
  }
}

async function answerLoop() {
  while (answerLoopOn) {
    const me = $("me").value.trim();
    if (!me) {
      await sleep(400);
      continue;
    }
    try {
      const r = await api(`/api/send-peer/get`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peerId: me, wait: true }),
      });
      const data = await r.json();
      if (data && data.sdp && data.from) {
        const from = data.from;
        const pc = pcs.get(from);
        if (pc) {
          await pc.setRemoteDescription({ type: "answer", sdp: data.sdp });
          statuses.set(from, "connected");
          setBadge();
          refreshPeers();
          log("connected ⇄", from);
        }
      }
    } catch (e) {
      log("answerLoop error:", e?.message || e);
    }
    await sleep(60);
  }
}

function ensureOfferLoopRunning() {
  if (!offerLoopOn) {
    offerLoopOn = true;
    offerLoop();
  }
}
function ensureAnswerLoopRunning() {
  if (!answerLoopOn) {
    answerLoopOn = true;
    answerLoop();
  }
}
function sleep(ms) {
  return new Promise((res) => setTimeout(res, ms));
}

// --------- Messaging ---------
$("send").onclick = () => {
  const msg = $("text").value.trim();
  if (!msg) return;
  for (const [, dc] of dcs.entries()) {
    if (dc.readyState === "open") dc.send(msg);
  }
  addMsg("me", msg);
  $("text").value = "";
};
$("text").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("send").click();
});

// --------- Boot ---------
(function boot() {
  refreshPeers(); // will toast if no channel
  offerLoop();
})();
window.addEventListener("beforeunload", () => {
  offerLoopOn = false;
  answerLoopOn = false;
});
