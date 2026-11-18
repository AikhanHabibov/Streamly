"use strict";
document.addEventListener("submit", (event) => {
  if (!event.target.matches("[data-moderation-report]")) return;
  const action = event.submitter?.value;
  if (["remove_video", "remove_comment", "stop_live", "block_account"].includes(action)) {
    const message = "Diese Moderationsmassnahme wirklich ausführen? Löschungen sind dauerhaft; Sperren können eine laufende Übertragung beenden.";
    if (!window.confirm(message)) event.preventDefault();
  }
});
