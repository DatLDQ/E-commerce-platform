/* Checkout: recompute shipping fee & total (server-side) when province/method changes. */
(function () {
  const form = document.getElementById("checkout-form");
  if (!form) return;
  const { vnd } = window.LU;
  const province = form.querySelector("[name=province]");
  async function refresh() {
    const method = form.querySelector("[name=delivery_method]:checked");
    const url = form.dataset.quoteUrl + "?province=" + encodeURIComponent(province.value) + "&method=" + (method ? method.value : "");
    const r = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (!r.ok) return;
    const d = await r.json();
    Object.entries(d.fees).forEach(([pk, info]) => {
      const opt = form.querySelector('[data-method="' + pk + '"]');
      if (!opt) return;
      opt.querySelector("[data-fee]").textContent = info.fee ? vnd(info.fee) : "Miễn phí";
      const radio = opt.querySelector("input");
      radio.disabled = !info.available;
      opt.classList.toggle("disabled", !info.available);
      if (!info.available && radio.checked) {
        radio.checked = false;
        const first = form.querySelector("[name=delivery_method]:not(:disabled)");
        if (first) { first.checked = true; return refresh(); }
      }
    });
    form.querySelector("[data-ship]").textContent = d.shipping_fee ? vnd(d.shipping_fee) : "Miễn phí";
    form.querySelector("[data-total]").textContent = vnd(d.total);
  }
  province.addEventListener("change", refresh);
  form.querySelectorAll("[name=delivery_method]").forEach((r) => r.addEventListener("change", refresh));
  refresh();
})();
