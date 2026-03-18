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
}


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

(function initERPUI() {
  const root = document.documentElement;
  const shell = document.getElementById("app-shell");
  const sidebarBtn = document.getElementById("sidebarToggleBtn");

  // Year
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Theme from storage
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") root.classList.add("dark");
    if (saved === "light") root.classList.remove("dark");
  } catch (_) {}

  // Compact mode (reduce animations/effects)
  try {
    const compact = localStorage.getItem("ui_compact");
    if (compact === "1") root.classList.add("compact");
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

  // Sidebar quick search (filters menu items)
  const menuSearch = document.getElementById("menuSearchInput");
  if (menuSearch) {
    const nav = document.getElementById("nav");
    const items = nav ? Array.from(nav.querySelectorAll("a.nav-item")) : [];
    const normalize = (str) => {
      const s = String(str || "").toLowerCase();
      if (typeof s.normalize === "function") {
        return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      }
      return s;
    };
    const getBestMatch = () => {
      const q = normalize(menuSearch.value.trim());
      if (!q) return null;
      let best = null;
      items.forEach((a, idx) => {
        const text = normalize(a.textContent);
        const href = normalize(a.getAttribute("href") || "");
        let score = 999;
        if (text === q || href === q) score = 0;
        else if (text.startsWith(q)) score = 1;
        else if (text.includes(q)) score = 2;
        else if (href.includes(q)) score = 3;
        if (score < 999 && (!best || score < best.score || (score === best.score && best.index > idx))) {
          best = { el: a, score, index: idx };
        }
      });
      return best;
    };
    const searchWrap = document.querySelector("#app-sidebar .menu-search");
    const searchBtn = document.querySelector("#app-sidebar .menu-search-btn");
    if (searchWrap) {
      searchWrap.addEventListener("click", (e) => {
        if (e.target === searchBtn || e.target.closest(".menu-search-btn")) return;
        menuSearch.focus();
      });
    }
    const filterMenu = () => {
      const q = normalize(menuSearch.value.trim());
      items.forEach((a) => {
        const text = normalize(a.textContent);
        const href = normalize(a.getAttribute("href") || "");
        const match = !q || text.includes(q) || href.includes(q);
        a.style.display = match ? "" : "none";
      });
    };
    menuSearch.addEventListener("input", filterMenu);
    menuSearch.addEventListener("keyup", (e) => {
      if (e.key !== "Enter") return;
      const best = getBestMatch();
      if (best && best.el) {
        window.location.href = best.el.getAttribute("href");
      } else if (menuSearch.value.trim()) {
        toast("Nenhum módulo encontrado", "warn");
      }
    });
    if (searchBtn) {
      searchBtn.addEventListener("click", () => {
        const best = getBestMatch();
        if (best && best.el) {
          window.location.href = best.el.getAttribute("href");
        } else if (menuSearch.value.trim()) {
          toast("Nenhum módulo encontrado", "warn");
        } else {
          menuSearch.focus();
        }
      });
    }
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

  // GSAP intro (subtle fade only, no floating movement)
  if (window.gsap) {
    try {
      window.gsap.set(".glass", { opacity: 0.96 });
      window.gsap.to(".glass", { opacity: 1, duration: 0.25, ease: "power1.out" });
    } catch (_) {}
  }

  // Sidebar toggle (desktop)
  if (shell && sidebarBtn) {
    const syncSidebarBtnState = () => {
      const hidden = shell.classList.contains("sidebar-hidden");
      sidebarBtn.setAttribute("title", hidden ? "Mostrar menu lateral" : "Ocultar menu lateral");
      sidebarBtn.setAttribute("aria-label", hidden ? "Mostrar menu lateral" : "Ocultar menu lateral");
    };
    try {
      const collapsed = localStorage.getItem("sidebar_hidden") === "1";
      if (collapsed) shell.classList.add("sidebar-hidden");
    } catch (_) {}
    syncSidebarBtnState();
    requestAnimationFrame(() => {
      shell.classList.add("sidebar-ready");
    });

    sidebarBtn.addEventListener("click", () => {
      shell.classList.toggle("sidebar-hidden");
      syncSidebarBtnState();
      try {
        localStorage.setItem("sidebar_hidden", shell.classList.contains("sidebar-hidden") ? "1" : "0");
      } catch (_) {}
    });
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
