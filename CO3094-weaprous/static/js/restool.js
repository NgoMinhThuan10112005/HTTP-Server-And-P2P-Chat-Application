"use strict";

const $ = (id) => document.getElementById(id);

// ----- presets -> headers textarea
$("headerPreset").addEventListener("change", (e) => {
  const v = e.target.value;
  if (!v) return;
  const ta = $("headers");
  ta.value = (ta.value ? ta.value.trimEnd() + "\n" : "") + v;
  e.target.value = "";
});

// quick x-channel helper
$("addXChan").onclick = () => {
  const v = $("channelQuick").value.trim();
  if (!v) return;
  const ta = $("headers");
  const line = `x-channel: ${v}`;
  ta.value = (ta.value ? ta.value.trimEnd() + "\n" : "") + line;
};

// send request
$("sendBtn").onclick = sendRequest;

async function sendRequest() {
  const method = $("method").value.trim();
  const url = $("url").value.trim();
  const bodyText = $("body").value;
  const withCreds = !!$("withCreds")?.checked;

  if (!url) {
    setResp("Status: (error)\n\nHeaders:\n—\n\nBody:\nURL cannot be empty");
    return;
  }

  const headersObj = parseHeadersLower($("headers").value);
  const opts = { method, headers: headersObj };
  if (withCreds) opts.credentials = "include";
  if (bodyText && !["GET", "HEAD"].includes(method)) opts.body = bodyText;

  const t0 = performance.now();
  try {
    const res = await fetch(url, opts);
    const t1 = performance.now();

    let headerLines = "";
    res.headers.forEach((v, k) => {
      headerLines += `${k}: ${v}\n`;
    });

    const ct = (res.headers.get("content-type") || "").toLowerCase();
    let text = await res.text();
    if (ct.includes("application/json")) {
      try {
        text = JSON.stringify(JSON.parse(text), null, 2);
      } catch {}
    }

    setResp(
      `Status: ${res.status} ${res.statusText}\n\nHeaders:\n${
        headerLines || "—"
      }\n\nBody:\n${text || "—"}`
    );
    $("timing").textContent = `Elapsed: ${(t1 - t0).toFixed(1)} ms`;
  } catch (err) {
    setResp(`Status: (network error)\n\nHeaders:\n—\n\nBody:\n${String(err)}`);
    $("timing").textContent = "";
  }
}

function parseHeadersLower(s) {
  return s.split("\n").reduce((acc, line) => {
    const i = line.indexOf(":");
    if (i > 0) {
      const k = line.slice(0, i).trim().toLowerCase();
      const v = line.slice(i + 1).trim();
      if (k) acc[k] = v;
    }
    return acc;
  }, {});
}

function setResp(txt) {
  $("response").textContent = txt;
}

// ---- P2P signaling tester ----
function logRelay(line) {
  const box = $("relayLog");
  box.textContent += (box.textContent ? "\n" : "") + line;
  box.scrollTop = box.scrollHeight;
}

$("offerPush").onclick = async () => {
  const from = $("relayFrom").value.trim();
  const to = $("relayTo").value.trim();
  const sdp = $("relaySdp").value.trim();
  if (!from || !to || !sdp) return logRelay("[offerPush] need From, To, SDP");
  try {
    const r = await fetch("/api/connect-peer", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ from, to, sdp }),
    });
    logRelay(`[offerPush] ${r.status} ${r.statusText}`);
    logRelay(await r.text());
  } catch (e) {
    logRelay("[offerPush] error " + e);
  }
};

$("offerPop").onclick = async () => {
  // pop for the callee (who should receive the offer)
  const peerId = $("relayTo").value.trim() || $("relayFrom").value.trim();
  const wait = $("relayWait").value === "true";
  if (!peerId) return logRelay("[offerPop] need peerId (use To or From)");
  try {
    const r = await fetch("/api/connect-peer/get", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ peerId, wait }),
    });
    const txt = await r.text();
    logRelay(`[offerPop] ${r.status} ${r.statusText}\n${txt}`);
    try {
      const j = JSON.parse(txt);
      if (j && j.sdp && j.from) {
        $("relayFrom").value = j.from;
        $("relaySdp").value = j.sdp;
      }
    } catch {}
  } catch (e) {
    logRelay("[offerPop] error " + e);
  }
};

$("answerPush").onclick = async () => {
  const from = $("relayFrom").value.trim(); // answerer
  const to = $("relayTo").value.trim(); // original offerer
  const sdp = $("relaySdp").value.trim();
  if (!from || !to || !sdp) return logRelay("[answerPush] need From, To, SDP");
  try {
    const r = await fetch("/api/send-peer", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ from, to, sdp }),
    });
    logRelay(`[answerPush] ${r.status} ${r.statusText}`);
    logRelay(await r.text());
  } catch (e) {
    logRelay("[answerPush] error " + e);
  }
};

$("answerPop").onclick = async () => {
  // pop for the caller (who should receive the answer)
  const peerId = $("relayFrom").value.trim() || $("relayTo").value.trim();
  const wait = $("relayWait").value === "true";
  if (!peerId) return logRelay("[answerPop] need peerId (use From or To)");
  try {
    const r = await fetch("/api/send-peer/get", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ peerId, wait }),
    });
    const txt = await r.text();
    logRelay(`[answerPop] ${r.status} ${r.statusText}\n${txt}`);
    try {
      const j = JSON.parse(txt);
      if (j && j.sdp && j.from) {
        $("relayTo").value = j.from;
        $("relaySdp").value = j.sdp;
      }
    } catch {}
  } catch (e) {
    logRelay("[answerPop] error " + e);
  }
};
