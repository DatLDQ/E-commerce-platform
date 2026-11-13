/* LevelBot chat widget — talks to /chatbot/tin-nhan/ (JSON). History kept per tab. */
(function () {
  "use strict";
  const fab = document.getElementById("chat-fab");
  const panel = document.getElementById("chat-panel");
  if (!fab || !panel) return;
  const body = document.getElementById("chat-body");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const endpoint = panel.dataset.endpoint;
  const KEY = "levelbot_history";
  let history = [];
  try { history = JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) {}

  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(history.slice(-40))); } catch (e) {} };
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";

  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

  function render(entry) {
    if (entry.role === "user") { body.appendChild(el("div", "msg user", entry.text)); return; }
    const d = entry.data;
    body.appendChild(el("div", "msg bot", d.reply));
    if (d.products && d.products.length) {
      const box = el("div", "msg-products");
      d.products.forEach((p) => {
        const a = el("a", "msg-product"); a.href = p.url;
        if (p.image) { const img = el("img"); img.src = p.image; img.alt = ""; a.appendChild(img); }
        const info = el("div"); info.appendChild(el("div", "small", p.name));
        const pr = el("div", "price", p.price); info.appendChild(pr);
        a.appendChild(info); box.appendChild(a);
      });
      body.appendChild(box);
    }
    const chips = el("div", "quick");
    (d.links || []).forEach((l) => { const a = el("a", "", l.text); a.href = l.url; chips.appendChild(a); });
    (d.quick_replies || []).forEach((q) => { const b = el("button", "", q); b.type = "button"; b.onclick = () => send(q); chips.appendChild(b); });
    if (chips.children.length) body.appendChild(chips);
  }

  function scroll() { body.scrollTop = body.scrollHeight; }

  async function send(text) {
    text = (text || "").trim();
    if (!text) return;
    const u = { role: "user", text };
    history.push(u); render(u); scroll(); save();
    const typing = el("div", "msg bot"); typing.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    body.appendChild(typing); scroll();
    try {
      const r = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ message: text }) });
      const data = await r.json();
      typing.remove();
      const b = { role: "bot", data };
      history.push(b); render(b); save();
    } catch (e) {
      typing.remove();
      render({ role: "bot", data: { reply: "Mất kết nối, bạn thử lại sau nhé." } });
    }
    scroll();
  }

  function open() {
    panel.classList.add("open"); fab.setAttribute("aria-expanded", "true");
    if (!body.children.length) {
      if (history.length) history.forEach(render);
      else render({ role: "bot", data: { reply: "Chào bạn 👋 Mình là LevelBot. Bạn đang tìm gear gì, ngân sách khoảng bao nhiêu?", quick_replies: ["Chuột FPS dưới 1 triệu", "Bàn phím cơ cho người mới", "Tai nghe không dây", "Phí ship bao nhiêu?"] } });
    }
    scroll(); input.focus();
  }
  function close() { panel.classList.remove("open"); fab.setAttribute("aria-expanded", "false"); fab.focus(); }

  fab.addEventListener("click", () => (panel.classList.contains("open") ? close() : open()));
  document.getElementById("chat-close").addEventListener("click", close);
  form.addEventListener("submit", (e) => { e.preventDefault(); const t = input.value; input.value = ""; send(t); });
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
})();
