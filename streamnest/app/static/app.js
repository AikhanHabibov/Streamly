"use strict";
const $ = (s, el = document) => el.querySelector(s);
const csrf = $('meta[name="csrf-token"]')?.content;
const toast = (message) => {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
};
const menu = $("[data-menu]");
const overlay = $("[data-overlay]");
function closeMenu() {
  document.body.classList.remove("menu-open");
  menu?.setAttribute("aria-expanded", "false");
  if (overlay) overlay.hidden = true;
}
menu?.addEventListener("click", () => {
  const opened = document.body.classList.toggle("menu-open");
  menu.setAttribute("aria-expanded", String(opened));
  overlay.hidden = !opened;
});
overlay?.addEventListener("click", closeMenu);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
document.querySelectorAll("[data-autosubmit]").forEach(el => {
  el.addEventListener("change", () => el.form.requestSubmit());
});
document.querySelectorAll("[data-confirm]").forEach(form => form.addEventListener("submit", e => {
  if (!window.confirm(form.dataset.confirm)) e.preventDefault();
}));
$("[data-back]")?.addEventListener("click", () => {
  if (history.length > 1) history.back(); else window.location.href = "/";
});
document.querySelectorAll("[data-share]").forEach(button => button.addEventListener("click", async () => {
  const url = button.dataset.share;
  try {
    if (navigator.share) await navigator.share({ title: document.title, url });
    else {
      await navigator.clipboard.writeText(url);
      toast("Link kopiert. Teile dein Lieblingsvideo!");
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      window.prompt("Öffentlicher Link zum Kopieren:", url);
    }
  }
}));
// Count a view only after 5 actual seconds of playback (or 80% for short videos).
// This is a basic engagement metric, not fraud-resistant audience measurement.
const player = $("#video-player");
if (player) {
  let watched = 0, previous = null, reported = false, reporting = false;
  player.addEventListener("pause", () => { previous = null; });
  player.addEventListener("seeking", () => { previous = null; });
  player.addEventListener("timeupdate", async () => {
    if (player.paused || player.seeking) { previous = null; return; }
    const current = player.currentTime;
    if (previous !== null && current >= previous && current - previous < 1.5) watched += (current - previous) / Math.max(player.playbackRate, .25);
    previous = current;
    if (!reported && !reporting && watched >= Math.min(5, player.duration * .8)) {
      reporting = true;
      try {
        const response = await fetch(`/api/videos/${player.dataset.videoId}/view`, {
          method: "POST", headers: { "X-CSRF-Token": csrf }, credentials: "same-origin"
        });
        if (response.ok) {
          const data = await response.json();
          $("#view-count").textContent = new Intl.NumberFormat("de-CH").format(data.views);
          reported = true;
        }
      } catch { /* Playback must continue even if statistics cannot be saved. */ }
      finally { reporting = false; }
    }
  });
}
const uploadForm = $("[data-upload]");
if (uploadForm) {
  const input = $("[data-video-file]");
  const zone = $("[data-dropzone]");
  const fileInfo = $("[data-file-info]");
  function showFile() {
    const file = input.files[0];
    if (!file) return;
    input.setCustomValidity("");
    if (!/\.(mp4|webm)$/i.test(file.name)) input.setCustomValidity("Bitte wähle MP4 oder WebM.");
    if (file.size > Number(input.dataset.maxSize)) input.setCustomValidity("Die Datei ist zu gross.");
    fileInfo.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
    zone.classList.add("has-file");
    input.reportValidity();
  }
  input.addEventListener("change", showFile);
  for (const event of ["dragenter", "dragover"]) zone.addEventListener(event, e => { e.preventDefault(); zone.classList.add("dragging"); });
  for (const event of ["dragleave", "drop"]) zone.addEventListener(event, e => { e.preventDefault(); zone.classList.remove("dragging"); });
  zone.addEventListener("drop", e => {
    if (!e.dataTransfer.files.length) return;
    const transfer = new DataTransfer();
    transfer.items.add(e.dataTransfer.files[0]);
    input.files = transfer.files;
    showFile();
  });
  uploadForm.addEventListener("submit", e => {
    e.preventDefault();
    if (!uploadForm.reportValidity()) return;
    const xhr = new XMLHttpRequest();
    const status = $("[data-upload-status]");
    const progress = $("progress", status);
    const text = $("[role='status']", status);
    const button = $("button[type=submit]", uploadForm);
    status.hidden = false;
    button.disabled = true;
    xhr.open("POST", "/upload");
    xhr.upload.addEventListener("progress", e => {
      if (e.lengthComputable) {
        progress.value = e.loaded / e.total * 100;
        text.textContent = progress.value >= 100 ? "Video wird geprüft und vorbereitet …" : `Wird hochgeladen … ${Math.round(progress.value)} %`;
      }
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 400 && xhr.responseURL.includes("/watch/")) {
        window.location.assign(xhr.responseURL);
      } else {
        button.disabled = false;
        const doc = new DOMParser().parseFromString(xhr.responseText, "text/html");
        let message = doc.querySelector(".error-page .muted")?.textContent;
        if (!message) { try { message = JSON.parse(xhr.responseText).detail; } catch {} }
        text.textContent = message || "Upload fehlgeschlagen. Bitte versuche es erneut.";
        toast(text.textContent);
      }
    };
    xhr.onerror = () => { button.disabled = false; text.textContent = "Netzwerkfehler. Bitte versuche es erneut."; };
    xhr.send(new FormData(uploadForm));
  });
}
