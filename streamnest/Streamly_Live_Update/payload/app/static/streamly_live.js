(() => {
"use strict";
const $ = s => document.querySelector(s);
$("[data-sl-reveal]")?.addEventListener("click", () => {
  const input = $("#sl-stream-key");
  input.type = input.type === "password" ? "text" : "password";
});
$("[data-sl-copy-key]")?.addEventListener("click", async e => {
  const input = $("#sl-stream-key");
  const button = e.currentTarget;
  try {
    await navigator.clipboard.writeText(input.value);
    button.textContent = "Kopiert";
  } catch {
    input.type = "text";
    input.select();
  }
});
const video = $("#sl-live-player");
if (!video) return;
const badge = $("#sl-live-status");
const offline = $("#sl-offline");
const message = $("#sl-player-message");
let hls = null, playingSource = "", isOnline = false;
function stop() {
  if (hls) { hls.destroy(); hls = null; }
  video.pause();
  video.removeAttribute("src");
  video.load();
  playingSource = "";
}
function play(source) {
  if (source === playingSource) return;
  stop();
  playingSource = source;
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = source;
    video.play().catch(() => {});
  } else if (window.Hls && Hls.isSupported()) {
    hls = new Hls({ enableWorker: false, lowLatencyMode: false, maxBufferLength: 15 });
    hls.loadSource(source);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    hls.on(Hls.Events.ERROR, (_, data) => {
      if (data.fatal) {
        message.textContent = "Wiedergabe unterbrochen. Ein neuer Verbindungsversuch folgt.";
        stop();
      }
    });
  } else {
    message.textContent = "Dieser Browser unterstützt die Live-Wiedergabe nicht oder hls.js fehlt. Prüfe die Installation.";
    playingSource = "";
  }
}
function update(online, source) {
  isOnline = online;
  offline.hidden = online;
  badge.textContent = online ? "LIVE" : "OFFLINE";
  badge.classList.toggle("online", online);
  if (online) play(source || video.dataset.source);
  else if (playingSource) stop();
}
update(video.dataset.online === "true", video.dataset.source);
let busy = false;
async function poll() {
  if (busy) return;
  busy = true;
  try {
    const response = await fetch(`/api/live/${encodeURIComponent(video.dataset.username)}/status`, { cache: "no-store" });
    if (response.status === 404) { update(false); message.textContent = "Der Streaming-Kanal wurde deaktiviert."; return; }
    if (!response.ok) throw new Error();
    const data = await response.json();
    message.textContent = data.available ? "" : "Der Streaming-Dienst ist derzeit nicht erreichbar.";
    update(data.online, data.playlist);
  } catch { message.textContent = "Status konnte nicht aktualisiert werden. Wir versuchen es erneut."; }
  finally { busy = false; }
}
setInterval(poll, 8000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
window.addEventListener("pagehide", stop);
poll();
})();
