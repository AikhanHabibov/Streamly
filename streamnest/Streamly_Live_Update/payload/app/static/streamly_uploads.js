(() => {
"use strict";
const form = document.querySelector("#sl-chunk-form");
if (!form) return;
const $ = s => form.querySelector(s);
const input = $("#sl-upload-file"), zone = $("#sl-dropzone"), info = $("#sl-file-info");
const box = $("#sl-upload-progress"), bar = $("progress"), message = $("#sl-upload-message");
const submit = $("button[type=submit]"), discard = $("#sl-discard-upload");
const csrf = form.elements.csrf.value;
const prefix = `streamly-upload:${form.dataset.user}:`;
const activeKey = prefix + "active";
const storage = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  remove(k) { try { localStorage.removeItem(k); } catch {} }
};
let uploadId = storage.get(activeKey), fingerprint = null, busy = false;
discard.hidden = !uploadId;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function report(text, error = false) {
  box.hidden = false;
  message.textContent = text;
  message.classList.toggle("sl-progress-error", error);
}
async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options, credentials: "same-origin", cache: "no-store",
    headers: { "X-CSRF-Token": csrf, ...(options.headers || {}) }
  });
  let data;
  try { data = await response.json(); }
  catch { data = { detail: "Unerwartete Serverantwort. Bitte prüfe deine Anmeldung und Verbindung." }; }
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : `Anfrage fehlgeschlagen (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}
function clearStored(id) {
  if (fingerprint && storage.get(fingerprint) === id) storage.remove(fingerprint);
  if (storage.get(activeKey) === id) storage.remove(activeKey);
}
function showFile() {
  const file = input.files[0];
  input.setCustomValidity("");
  if (!file) return;
  if (!/\.(mp4|webm)$/i.test(file.name)) input.setCustomValidity("Bitte wähle MP4 oder WebM.");
  if (file.size > Number(form.dataset.maxSize)) input.setCustomValidity("Die Datei überschreitet das Videolimit.");
  info.textContent = `${file.name} · ${(file.size / 1024 ** 2).toFixed(1)} MiB`;
  zone.classList.add("has-file");
  fingerprint = prefix + JSON.stringify([file.name, file.size, file.lastModified]);
  uploadId = storage.get(fingerprint) || storage.get(activeKey);
  discard.hidden = !uploadId;
  input.reportValidity();
}
input.addEventListener("change", showFile);
["dragenter", "dragover"].forEach(name => zone.addEventListener(name, e => { e.preventDefault(); zone.classList.add("dragging"); }));
["dragleave", "drop"].forEach(name => zone.addEventListener(name, e => { e.preventDefault(); zone.classList.remove("dragging"); }));
zone.addEventListener("drop", e => {
  if (!e.dataTransfer.files.length) return;
  const files = new DataTransfer();
  files.items.add(e.dataTransfer.files[0]);
  input.files = files.files;
  showFile();
});
discard.addEventListener("click", async () => {
  if (!uploadId || busy || !confirm("Gespeicherte Teile dieses Uploads wirklich löschen?")) return;
  try {
    await api(`/api/uploads/${uploadId}`, { method: "DELETE" });
    clearStored(uploadId);
    uploadId = null;
    discard.hidden = true;
    report("Gespeicherten Upload verworfen. Du kannst neu beginnen.");
  } catch (err) { report(err.message, true); }
});
async function waitForVideo(id) {
  let failures = 0;
  for (;;) {
    report("Übertragung abgeschlossen. Video wird geprüft und Vorschaubild erstellt …");
    try {
      const status = await api(`/api/uploads/${id}/status`);
      failures = 0;
      if (status.state === "done") {
        clearStored(id);
        window.location.assign(`/watch/${status.video_id}`);
        return;
      }
      if (status.state === "failed") throw Object.assign(new Error(status.error || "Verarbeitung fehlgeschlagen."), { terminal: true });
    } catch (err) {
      if (err.terminal || err.status === 401 || err.status === 404 || ++failures > 10) throw err;
      report("Verbindung unterbrochen. Der Server kann im Hintergrund weiterarbeiten; wir prüfen erneut …");
    }
    await sleep(2000);
  }
}
form.addEventListener("submit", async e => {
  e.preventDefault();
  if (busy || !form.reportValidity()) return;
  const file = input.files[0];
  if (!file) return;
  busy = true; submit.disabled = true; discard.disabled = true;
  try {
    const metadata = {
      filename: file.name, size: file.size, title: form.elements.title.value,
      description: form.elements.description.value, category: form.elements.category.value
    };
    fingerprint = prefix + JSON.stringify([file.name, file.size, file.lastModified]);
    uploadId = storage.get(fingerprint);
    let status = null;
    if (uploadId) {
      try { status = await api(`/api/uploads/${uploadId}/status`); }
      catch (err) { if (err.status !== 404) throw err; clearStored(uploadId); uploadId = null; }
    }
    if (status?.state === "done") { clearStored(uploadId); window.location.assign(`/watch/${status.video_id}`); return; }
    if (status?.state === "processing") { await waitForVideo(uploadId); return; }
    if (status?.state === "failed") {
      await api(`/api/uploads/${uploadId}`, { method: "DELETE" });
      clearStored(uploadId); uploadId = null; status = null;
    }
    if (!uploadId) {
      const initialized = await api("/api/uploads/init", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(metadata)
      });
      uploadId = initialized.id;
      status = { received: [], chunk_size: initialized.chunk_size };
      storage.set(fingerprint, uploadId);
      storage.set(activeKey, uploadId);
    } else {
      await api(`/api/uploads/${uploadId}/metadata`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(metadata)
      });
    }
    discard.hidden = false;
    const chunkSize = status.chunk_size, count = Math.ceil(file.size / chunkSize);
    const received = new Set(status.received || []);
    let transferred = [...received].reduce((sum, index) => sum + Math.min(chunkSize, file.size - index * chunkSize), 0);
    for (let index = 0; index < count; index++) {
      if (received.has(index)) continue;
      const blob = file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize));
      bar.value = transferred / file.size * 100;
      report(`${Math.floor(bar.value)} % übertragen · Teil ${index + 1} von ${count}`);
      for (let attempt = 0; ; attempt++) {
        try {
          await api(`/api/uploads/${uploadId}/chunks/${index}`, {
            method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: blob
          });
          break;
        } catch (err) {
          if ([400, 401, 403, 404, 409, 413, 507].includes(err.status) || attempt >= 2) throw err;
          report(`Verbindungsfehler bei Teil ${index + 1}. Erneuter Versuch …`);
          await sleep(1000 * (attempt + 1));
        }
      }
      transferred += blob.size;
    }
    bar.value = 100;
    await api(`/api/uploads/${uploadId}/finish`, { method: "POST" });
    await waitForVideo(uploadId);
  } catch (err) {
    report(`${err.message} Gespeicherte Teile bleiben für bis zu 24 Stunden verfügbar.`, true);
    submit.textContent = "Upload fortsetzen / erneut versuchen";
  } finally {
    busy = false; submit.disabled = false; discard.disabled = false;
  }
});
})();
