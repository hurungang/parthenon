/**
 * Parthenon JavaScript SDK — third-party agent integration.
 *
 * A *client* credential grants access to one agent type's input interface only.
 * Use a `publishable` credential in the browser and a `secret` credential
 * server-side. The credential is NOT an identity and never grants tool access.
 */

export class ParthenonError extends Error {}

export class ParthenonClient {
  /**
   * @param {{ baseUrl: string, credential: string }} opts
   */
  constructor({ baseUrl, credential }) {
    if (!baseUrl) throw new ParthenonError('baseUrl is required');
    if (!credential) throw new ParthenonError('credential is required');
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.credential = credential;
  }

  async _request(method, path, body) {
    const res = await fetch(this.baseUrl + path, {
      method,
      headers: {
        Authorization: 'Bearer ' + this.credential,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new ParthenonError(`Parthenon request failed: ${res.status} ${text}`);
    }
    return res.json();
  }

  /** Return the client's white-label widget/theme config. */
  config() {
    return this._request('GET', '/integrate/config');
  }

  /** Send a one-shot typed request to a non-conversational agent type. */
  submit(input) {
    return this._request('POST', '/integrate/submit', { input });
  }

  /** Start a stateful conversation session (conversational agent types). */
  startConversation() {
    return this._request('POST', '/integrate/conversations');
  }

  /** Send a message within a stateful conversation and get the reply. */
  sendMessage(conversationId, message) {
    return this._request('POST', `/integrate/conversations/${conversationId}/messages`, { message });
  }

  /** End a stateful conversation session. */
  endConversation(conversationId) {
    return this._request('POST', `/integrate/conversations/${conversationId}/end`);
  }
}

// ── Format detection + markdown rendering (mirrors the Control Center) ──────
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** Render a reply: HTML (sanitized) / JSON / markdown. Returns an HTML string. */
export function renderRich(text) {
  const raw = String(text == null ? '' : text);
  const t = raw.trim();
  if (t.startsWith('{') || t.startsWith('[')) {
    try { return '<pre>' + escapeHtml(JSON.stringify(JSON.parse(t), null, 2)) + '</pre>'; } catch (e) { /* not JSON */ }
  }
  // Prefer marked + DOMPurify when the host page provides them (proper GFM tables etc.).
  if (typeof window !== 'undefined' && typeof window.marked !== 'undefined' && typeof window.DOMPurify !== 'undefined') {
    return window.DOMPurify.sanitize(window.marked.parse(raw));
  }
  return renderMarkdown(raw);
}

function sanitizeHtml(html) {
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach((n) => n.remove());
    doc.querySelectorAll('*').forEach((node) => {
      for (const attr of Array.from(node.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on')) node.removeAttribute(attr.name);
        if ((name === 'href' || name === 'src') && String(attr.value || '').toLowerCase().startsWith('javascript:')) {
          node.removeAttribute(attr.name);
        }
      }
    });
    return doc.body.innerHTML;
  } catch (e) { return escapeHtml(html); }
}

function renderMarkdown(text) {
  let s = escapeHtml(text);
  s = s.replace(/```[^\n]*\n?([\s\S]*?)```/g, (_, code) => '<pre><code>' + code.replace(/\n$/, '') + '</code></pre>');
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  s = s.replace(/^######\s+(.*)$/gm, '<h6>$1</h6>')
       .replace(/^#####\s+(.*)$/gm, '<h5>$1</h5>')
       .replace(/^####\s+(.*)$/gm, '<h4>$1</h4>')
       .replace(/^###\s+(.*)$/gm, '<h3>$1</h3>')
       .replace(/^##\s+(.*)$/gm, '<h2>$1</h2>')
       .replace(/^#\s+(.*)$/gm, '<h1>$1</h1>');
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>').replace(/_([^_\n]+)_/g, '<em>$1</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  s = s.replace(/^&gt;\s?(.*)$/gm, '<blockquote>$1</blockquote>');
  s = s.replace(/^---+$/gm, '<hr>');
  s = s.replace(/^(?:[-*])\s+(.*)$/gm, '<li>$1</li>');
  s = s.replace(/(?:^|\n)((?:<li>[\s\S]*?<\/li>\n?)+)/g, (_, items) => '\n<ul>' + items.trim() + '</ul>\n');
  return s.split(/\n{2,}/).map((block) => {
    const t = block.trim();
    if (!t) return '';
    if (/^<(h[1-6]|pre|ul|ol|blockquote|hr|table)/.test(t)) return t;
    return '<p>' + t.replace(/\n/g, '<br>') + '</p>';
  }).join('');
}

/**
 * Minimal embeddable chat widget with stateful conversations and rich rendering.
 * `mount(selector, { baseUrl, publishableKey, theme })`.
 */
export const ParthenonChat = {
  mount(selector, opts) {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!el) throw new ParthenonError('ParthenonChat: selector not found');
    const client = new ParthenonClient({ baseUrl: opts.baseUrl, credential: opts.publishableKey });
    const theme = opts.theme || {};
    const color = theme.color || '#6D28D9';
    let conversationId = null;

    el.innerHTML =
      '<div style="font-family:sans-serif;max-width:420px">' +
      `<div style="background:${color};color:#fff;padding:10px 14px;border-radius:8px 8px 0 0;font-weight:600">${theme.name || 'Assistant'}</div>` +
      '<div class="pc-log" style="border:1px solid #ddd;border-top:none;padding:12px;min-height:180px;max-height:320px;overflow:auto"></div>' +
      '<div style="display:flex;border:1px solid #ddd;border-top:none">' +
      '<input class="pc-in" placeholder="Type a message…" style="flex:1;border:none;padding:10px;outline:none">' +
      `<button class="pc-send" style="border:none;background:${color};color:#fff;padding:0 16px">Send</button></div></div>`;

    const log = el.querySelector('.pc-log');
    const input = el.querySelector('.pc-in');
    const add = (role, text) => {
      const d = document.createElement('div');
      d.style.margin = '6px 0';
      if (role === 'user') {
        d.textContent = 'You: ' + text;
      } else {
        d.innerHTML = '<strong>Bot:</strong> ' + renderRich(text);
      }
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    };
    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      add('user', text);
      input.value = '';
      try {
        if (!conversationId) {
          const c = await client.startConversation();
          conversationId = c.conversation_id;
        }
        const d = await client.sendMessage(conversationId, text);
        add('bot', d.reply || '(no reply)');
      } catch (e) {
        add('bot', 'Error: ' + e.message);
      }
    };
    el.querySelector('.pc-send').addEventListener('click', send);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') send();
    });
  },
};

export default ParthenonClient;
