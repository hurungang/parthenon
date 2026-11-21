/* Parthenon UX prototype — maximise dialog (relocated; shared by every page that shows
   long agent output: chat, execution details, result repository, agent outputs). */
/* ── MAXIMIZE DIALOG (improve-agent-response-rendering) ── */
window.maxOpen = function(contentId, title) {
  title = title || 'Maximized View';
  var sourceEl = null;

  if (contentId === 'chat-msg-1') {
    var msgs1 = document.querySelectorAll('.msg-agent .msg-bubble');
    sourceEl = msgs1.length > 0 ? msgs1[0] : null;
  } else if (contentId === 'chat-msg-2') {
    var msgs2 = document.querySelectorAll('.msg-agent .msg-bubble');
    sourceEl = msgs2.length > 1 ? msgs2[1] : null;
  } else if (contentId === 'exec-result') {
    sourceEl = document.getElementById('exec-result-content');
  } else {
    var el = document.getElementById(contentId);
    if (el) sourceEl = el;
  }

  var content = document.getElementById('maxDialogContent');
  var titleEl = document.getElementById('maxDialogTitle');
  content.innerHTML = '';

  if (sourceEl) {
    var clone = sourceEl.cloneNode(true);
    // Normalize styles for dialog viewing
    clone.style.maxWidth = '100%';
    clone.style.fontSize = '14px';
    clone.style.lineHeight = '1.7';
    content.appendChild(clone);
  }

  titleEl.textContent = title;
  document.getElementById('maxDialogOverlay').classList.add('open');
};

window.maxClose = function() {
  document.getElementById('maxDialogOverlay').classList.remove('open');
};

// Close maximize dialog on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    var overlay = document.getElementById('maxDialogOverlay');
    if (overlay && overlay.classList.contains('open')) {
      maxClose();
    }
  }
});

