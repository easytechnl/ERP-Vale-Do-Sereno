// Global UI helpers for ERP (MVP)
// - Theme toggle (dark/light)
// - Lucide icons
// - Tooltips (tippy)
// - Ripple effect
// - Subtle particles background (tsParticles)
// - GSAP intro animations
// - VanillaTilt (premium hover)
// - CountUp (if elements exist)
// - Toast helper (existing)

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = "fixed top-5 right-5 z-[9999] rounded-xl px-4 py-3 text-sm shadow-lg border";
  const colors = {
    info: "bg-white/90 text-slate-800 border-slate-200",
    ok: "bg-emerald-50 text-emerald-900 border-emerald-200",
    warn: "bg-amber-50 text-amber-900 border-amber-200",
    err: "bg-rose-50 text-rose-900 border-rose-200",
  };
  el.className += " " + (colors[type] || colors.info);
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);


async function postJSON(url, payload = null) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : null,
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

async function postForm(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData });
  if (!res.ok) throw new Error(await res.text());
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return await res.json();
  return await res.text();
}

}

(function initERPUI() {
  const root = document.documentElement;

  // Year
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Theme from storage
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") root.classList.add("dark");
    if (saved === "light") root.classList.remove("dark");
  } catch (_) {}

  // Theme toggle
  const themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      root.classList.toggle("dark");
      try {
        localStorage.setItem("theme", root.classList.contains("dark") ? "dark" : "light");
      } catch (_) {}
    });
  }

  // Lucide icons
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }

  // Tooltips
  if (window.tippy) {
    window.tippy("[data-tip]", { animation: "scale", theme: "light-border" });
  }


  // Copy helper (ex.: mensagem pronta de boleto)
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const text = btn.getAttribute("data-copy") || "";
    try {
      await navigator.clipboard.writeText(text);
      toast("Mensagem copiada!", "ok");
    } catch (_) {
      toast("Não consegui copiar. Copie manualmente.", "warn");
    }
  });

  // Forms rápidos (ex.: atualizar status do boleto)
  document.addEventListener("submit", async (e) => {
    const f = e.target.closest("form[data-status-form]");
    if (!f) return;
    e.preventDefault();
    try {
      await postForm(f.action, new FormData(f));
      toast("Status atualizado. Atualizando...", "ok");
      setTimeout(() => location.reload(), 600);
    } catch (err) {
      toast(String(err.message || err), "err");
    }
  });

  // Ripple
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".ripple");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const rip = document.createElement("span");
    rip.className = "rip";
    rip.style.left = x + "px";
    rip.style.top = y + "px";
    btn.appendChild(rip);
    setTimeout(() => rip.remove(), 650);
  });

  // Particles (subtle)
  (async () => {
    if (!window.tsParticles || !document.getElementById("tsparticles")) return;
    try {
      await window.tsParticles.load("tsparticles", {
        fullScreen: { enable: false },
        background: { color: { value: "transparent" } },
        fpsLimit: 60,
        particles: {
          number: { value: 34, density: { enable: true, area: 900 } },
          color: { value: ["#08843b", "#c6c335"] },
          links: { enable: true, distance: 140, opacity: 0.18, width: 1, color: "#08843b" },
          move: { enable: true, speed: 0.7, outModes: { default: "out" } },
          opacity: { value: 0.35 },
          size: { value: { min: 1, max: 3 } }
        },
        interactivity: {
          events: { onHover: { enable: true, mode: "repulse" }, resize: true },
          modes: { repulse: { distance: 110, duration: 0.4 } }
        },
        detectRetina: true
      });
    } catch (_) {
      // ignore
    }
  })();

  // GSAP intro
  if (window.gsap) {
    try {
      window.gsap.set(".glass", { opacity: 0, y: 14 });
      window.gsap.to(".glass", { opacity: 1, y: 0, duration: 0.6, ease: "power2.out", stagger: 0.06 });

      window.gsap.from(".nav-item", {
        opacity: 0,
        x: -10,
        duration: 0.5,
        ease: "power2.out",
        stagger: 0.05,
        delay: 0.15,
      });
    } catch (_) {}
  }

  // Tilt
  if (window.VanillaTilt) {
    try {
      window.VanillaTilt.init(document.querySelectorAll("[data-tilt]"), {
        max: 6,
        speed: 700,
        glare: true,
        "max-glare": 0.22,
        scale: 1.01
      });
    } catch (_) {}
  }

  // CountUp (optional)
  if (window.countUp && window.countUp.CountUp) {
    try {
      document.querySelectorAll(".count[data-value]").forEach((el) => {
        const v = Number(el.dataset.value || "0");
        const decimals = String(v).includes(".") ? 1 : 0;
        const cu = new window.countUp.CountUp(el, v, {
          duration: 1.2,
          decimalPlaces: decimals,
          separator: ".",
          decimal: ","
        });
        if (!cu.error) cu.start();
      });
    } catch (_) {}
  }
})();
