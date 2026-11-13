/* LevelUp Gear — storefront interactions (vanilla JS, progressive enhancement:
   every feature also works without JavaScript through normal form posts). */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ($("[name=csrfmiddlewaretoken]") || {}).value;
  const vnd = (n) => new Intl.NumberFormat("vi-VN").format(n) + "₫";
  window.LU = { $, $$, csrf, vnd };

  /* ---- toast helper ---- */
  function toast(text, type = "success") {
    let box = $(".toasts");
    if (!box) { box = document.createElement("div"); box.className = "toasts"; box.setAttribute("role", "status"); document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast " + type;
    t.textContent = text;
    const b = document.createElement("button"); b.textContent = "×"; b.setAttribute("aria-label", "Đóng"); b.onclick = () => t.remove();
    t.appendChild(b); box.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }
  window.LU.toast = toast;
  // Buttons that must not be pressed twice (cancel order, buy again…)
  $$("button[data-once]").forEach((b) => b.form && b.form.addEventListener("submit", () => setTimeout(() => (b.disabled = true))));
  $$(".toast [data-dismiss]").forEach((b) => (b.onclick = () => b.parentElement.remove()));
  setTimeout(() => $$(".toasts .toast").forEach((t) => t.remove()), 6000);

  /* ---- theme toggle ---- */
  const themeBtn = $("[data-theme-toggle]");
  function syncThemeIcon() {
    const light = document.documentElement.dataset.theme === "light";
    if (themeBtn) themeBtn.querySelector("use").setAttribute("href", light ? "#i-moon" : "#i-sun");
  }
  syncThemeIcon();
  themeBtn && themeBtn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    syncThemeIcon();
  });

  /* ---- drawer & dropdowns ---- */
  const drawer = $("#drawer");
  $$("[data-open-drawer]").forEach((b) => b.addEventListener("click", () => { drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); b.setAttribute("aria-expanded", "true"); }));
  $$("[data-close-drawer]").forEach((b) => b.addEventListener("click", () => { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); }));
  $$("[data-dropdown]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const dd = btn.closest(".dropdown");
      const open = dd.classList.toggle("open");
      btn.setAttribute("aria-expanded", open);
    });
  });
  document.addEventListener("click", () => $$(".dropdown.open").forEach((d) => d.classList.remove("open")));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $$(".dropdown.open").forEach((d) => d.classList.remove("open")); drawer && drawer.classList.remove("open"); }
  });

  /* ---- cookie consent (PDP Law 91/2025/QH15: consent must be explicit) ---- */
  $$("[data-cookie]").forEach((b) => b.addEventListener("click", () => {
    document.cookie = "cookie_consent=" + b.dataset.cookie + ";path=/;max-age=" + 60 * 60 * 24 * 180 + ";SameSite=Lax";
    $("#cookie-banner").remove();
  }));

  /* ---- add to cart via fetch (falls back to normal POST) ---- */
  function setCartCount(n) {
    $$("[data-cart-count]").forEach((el) => { el.textContent = n; el.hidden = !n; });
  }
  $$("form[data-add-to-cart]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      if (e.submitter && e.submitter.name === "buy_now") return; // let "Mua ngay" go to checkout
      e.preventDefault();
      const btn = form.querySelector("button");
      btn.disabled = true;
      try {
        const r = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf() } });
        const data = await r.json();
        setCartCount(data.cart_count);
        toast(data.message, data.ok && !data.capped ? "success" : "warning");
      } catch (err) { form.submit(); }
      btn.disabled = false;
    });
  });

  /* ---- quantity steppers ---- */
  $$(".qty").forEach((q) => {
    const input = q.querySelector("input");
    q.querySelectorAll("button[data-step]").forEach((b) => b.addEventListener("click", () => {
      const max = parseInt(input.max || "99", 10), min = parseInt(input.min || "1", 10);
      input.value = Math.min(max, Math.max(min, (parseInt(input.value, 10) || 1) + parseInt(b.dataset.step, 10)));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }));
    // A typed amount above the limit is pulled back to it, and the shopper is told why.
    input.addEventListener("change", () => {
      const max = parseInt(input.max, 10), val = parseInt(input.value, 10);
      if (max > 0 && val > max) {
        input.value = max;
        toast("Bạn có thể mua tối đa " + max + " sản phẩm này trong một đơn — số lượng đã được điều chỉnh về " + max + ".", "warning");
      }
    });
  });

  /* ---- cart page: live quantity update ---- */
  $$("form[data-cart-line]").forEach((form) => {
    const input = form.querySelector("input[name=quantity]");
    let timer;
    input.addEventListener("change", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const r = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf() } });
        const d = await r.json();
        if (d.reload || !d.quantity) return location.reload();
        if (d.message) toast(d.message, "warning");
        input.value = d.quantity;
        form.closest(".cart-line").querySelector("[data-line-total]").textContent = vnd(d.line_total);
        $("[data-subtotal]").textContent = vnd(d.subtotal);
        $("[data-discount]") && ($("[data-discount]").textContent = "-" + vnd(d.discount));
        $("[data-total]").textContent = vnd(d.total);
        const gap = $("[data-free-ship]");
        if (gap) gap.innerHTML = d.free_ship_gap > 0 ? "Mua thêm <b>" + vnd(d.free_ship_gap) + "</b> để được miễn phí giao hàng" : "🎉 Đơn của bạn được <b>miễn phí giao hàng</b>";
        setCartCount(d.cart_count);
        const units = $("[data-cart-units]");
        if (units) units.textContent = d.cart_count;
      }, 350);
    });
  });

  /* ---- product gallery & tabs ---- */
  $$(".thumbs button").forEach((b) => b.addEventListener("click", () => {
    $(".gallery-main img").src = b.dataset.src;
    $$(".thumbs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
  }));
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => { x.classList.remove("active"); x.setAttribute("aria-selected", "false"); });
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    b.classList.add("active"); b.setAttribute("aria-selected", "true");
    $("#" + b.getAttribute("aria-controls")).classList.add("active");
  }));
  // A link to #reviews (e.g. "Đánh giá" from an order) opens that tab.
  if (location.hash) {
    const tab = $('.tabs button[aria-controls="' + location.hash.slice(1).replace(/[^\w-]/g, "") + '"]');
    if (tab) { tab.click(); tab.scrollIntoView({ block: "start" }); }
  }

  /* ---- hero slider ---- */
  // One shared row of dots ([data-hero-dots], after the slides): dot k shows slide k.
  const slides = $$("[data-slide]");
  const dots = $$("[data-hero-dots] button");
  if (slides.length > 1 && dots.length === slides.length) {
    let i = 0, timer;
    const show = (n) => {
      slides.forEach((s, k) => (s.hidden = k !== n));
      dots.forEach((d, k) => { d.classList.toggle("active", k === n); if (k === n) d.setAttribute("aria-current", "true"); else d.removeAttribute("aria-current"); });
      i = n;
    };
    const autoplay = () => {
      clearInterval(timer);
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) timer = setInterval(() => show((i + 1) % slides.length), 6000);
    };
    dots.forEach((d, k) => d.addEventListener("click", () => { show(k); autoplay(); }));
    const box = slides[0].parentNode;  // pause while the pointer is over the banner
    box.addEventListener("mouseenter", () => clearInterval(timer));
    box.addEventListener("mouseleave", autoplay);
    show(0);
    autoplay();
  }

  /* ---- filters drawer (mobile) ---- */
  $$("[data-filters-toggle]").forEach((b) => b.addEventListener("click", () => $(".filters").classList.toggle("open")));
  $$("form[data-auto-submit] input[type=checkbox], form[data-auto-submit] input[type=radio]").forEach((el) =>
    el.addEventListener("change", () => el.form.submit()));

  /* ---- wishlist toggle ---- */
  $$("form[data-wishlist]").forEach((form) => form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (r.redirected || !r.ok) return (location.href = form.dataset.login);
    const d = await r.json();
    const btn = form.querySelector("button");
    btn.classList.toggle("btn-secondary", d.in_wishlist);
    btn.querySelector("span").textContent = d.in_wishlist ? "Đã yêu thích" : "Yêu thích";
    toast(d.in_wishlist ? "Đã thêm vào danh sách yêu thích" : "Đã bỏ khỏi danh sách yêu thích");
  }));

  /* ---- compare (stored per browser) ---- */
  const CMP = "compare_ids";
  const getCmp = () => { try { return JSON.parse(localStorage.getItem(CMP) || "[]"); } catch (e) { return []; } };
  $$("[data-compare]").forEach((b) => b.addEventListener("click", () => {
    let ids = getCmp().filter((x) => x !== b.dataset.compare);
    ids.unshift(b.dataset.compare); ids = ids.slice(0, 4);
    try { localStorage.setItem(CMP, JSON.stringify(ids)); } catch (e) {}
    location.href = b.dataset.url + "?ids=" + ids.join(",");
  }));
  // remove links on the compare page keep the stored list in step
  $$("[data-compare-set]").forEach((a) => a.addEventListener("click", () => {
    const ids = a.dataset.compareSet ? a.dataset.compareSet.split(",") : [];
    try { localStorage.setItem(CMP, JSON.stringify(ids)); } catch (e) {}
  }));

  /* ---- search autocomplete ---- */
  $$("form[data-autocomplete]").forEach((form) => {
    const input = form.querySelector("input[name=q]");
    let panel, timer, active = -1;
    const close = () => { panel && panel.remove(); panel = null; active = -1; };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) return close();
      timer = setTimeout(async () => {
        const r = await fetch(form.dataset.autocomplete + "?q=" + encodeURIComponent(q));
        const d = await r.json();
        close();
        if (!d.results.length) return;
        panel = document.createElement("div");
        panel.className = "ac-panel"; panel.setAttribute("role", "listbox");
        const link = (href, cls, text) => {
          const a = document.createElement("a");
          a.href = href; a.setAttribute("role", "option");
          if (cls) a.className = cls;
          if (text) a.textContent = text;
          return a;
        };
        // the categories that match, with how many products each ("Chuột gaming 6"), so nothing is hidden
        if (d.categories && d.categories.length > 1) {
          const cats = document.createElement("div");
          cats.className = "ac-cats";
          d.categories.forEach((c) => {
            const a = link(c.url, "", c.name + " ");
            const n = document.createElement("b"); n.textContent = c.count; a.appendChild(n);
            cats.appendChild(a);
          });
          panel.appendChild(cats);
        }
        d.results.forEach((p) => {
          const a = link(p.url);
          a.innerHTML = (p.image ? '<img alt="" src="' + p.image + '">' : "") + "<span></span>";
          a.querySelector("span").innerHTML = "<div></div><div class='ac-meta'><span class='price'></span> · <span></span></div>";
          a.querySelector("span div").textContent = p.name;
          a.querySelector(".price").textContent = vnd(p.price);
          a.querySelector(".ac-meta span:last-child").textContent = p.category;
          panel.appendChild(a);
        });
        if (d.total > d.results.length) panel.appendChild(link(d.all_url, "ac-all", "Xem tất cả " + d.total + " kết quả"));
        form.appendChild(panel);
      }, 200);
    });
    input.addEventListener("keydown", (e) => {
      if (!panel) return;
      const items = $$("a", panel);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((x, k) => x.classList.toggle("active", k === active));
      } else if (e.key === "Enter" && active >= 0) { e.preventDefault(); location.href = items[active].href; }
      else if (e.key === "Escape") close();
    });
    document.addEventListener("click", (e) => { if (!form.contains(e.target)) close(); });
  });
})();
