/* DD 监控室 CE — Live Stage prototype interactions
   Dependency-free. ?capture=1 freezes decorative motion for screenshots. */

(() => {
  const root = document.documentElement;
  const params = new URLSearchParams(window.location.search);
  const capture = params.has("capture");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (capture) root.classList.add("capture");

  /* ---------- layout preview ---------- */

  const modes = {
    split: {
      label: "横屏 · 平分布局",
      quality: "16 路 / 原画",
      caption: "当前：横屏 · 平分布局",
      src: "assets/wall-landscape.jpg",
      alt: "DD监控室 CE 横屏平分布局截图",
      portrait: false,
    },
    hero: {
      label: "横屏 · 大带小",
      quality: "16 路 / 原画",
      caption: "当前：横屏 · 大带小",
      src: "assets/wall-landscape.jpg",
      alt: "DD监控室 CE 横屏大带小布局截图",
      portrait: false,
    },
    danmaku: {
      label: "横屏 · 弹幕布局",
      quality: "16 路 / 弹幕",
      caption: "当前：横屏 · 弹幕布局",
      src: "assets/wall-danmaku.jpg",
      alt: "DD监控室 CE 弹幕布局截图",
      portrait: false,
    },
    portrait: {
      label: "竖屏 · 主画面铺满",
      quality: "竖屏 / 原画",
      caption: "当前：竖屏 · 主画面铺满",
      src: "assets/wall-portrait.jpg",
      alt: "DD监控室 CE 竖屏布局截图",
      portrait: true,
    },
  };

  const tabs = [...document.querySelectorAll("[data-mode]")];
  const rows = [...document.querySelectorAll("[data-mode-row]")];
  const frame = document.getElementById("layout-frame");
  const image = document.getElementById("layout-image");
  const label = document.getElementById("layout-label");
  const quality = document.getElementById("layout-quality");
  const caption = document.getElementById("layout-caption");

  const selectMode = (name) => {
    const mode = modes[name];
    if (!mode || !image || !frame) return;

    tabs.forEach((tab) => {
      const active = tab.dataset.mode === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-pressed", String(active));
    });
    rows.forEach((row) => {
      row.classList.toggle("is-active", row.dataset.modeRow === name);
    });

    image.src = mode.src;
    image.alt = mode.alt;
    label.textContent = mode.label;
    quality.textContent = mode.quality;
    caption.textContent = mode.caption;
    frame.classList.toggle("is-portrait", mode.portrait);
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectMode(tab.dataset.mode));
  });

  const startMode = params.get("mode");
  if (startMode && modes[startMode]) selectMode(startMode);

  /* ---------- small control states ---------- */

  document.querySelectorAll(".route").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      button.classList.toggle("is-on");
    });
  });

  document.querySelectorAll(".rec-pill").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      const active = button.classList.toggle("is-rec");
      button.lastChild.textContent = active ? "停止" : "录制";
    });
  });

  document.querySelectorAll(".switch").forEach((button) => {
    button.addEventListener("click", () => {
      const active = button.classList.toggle("is-on");
      button.setAttribute("aria-pressed", String(active));
    });
  });

  const save = document.querySelector(".save-clip");
  if (save) {
    save.addEventListener("click", () => {
      const original = save.textContent;
      save.textContent = "已加入导出 ✓";
      save.disabled = true;
      window.setTimeout(() => {
        save.textContent = original;
        save.disabled = false;
      }, 1800);
    });
  }

  /* ---------- gentle pointer parallax ---------- */

  const stage = document.getElementById("hero-stage");
  const screen = document.querySelector(".stage-card--screen");

  if (stage && screen && !capture && !reduceMotion) {
    let frameId = 0;
    let target = { x: 0, y: 0 };

    const apply = () => {
      frameId = 0;
      stage.style.setProperty("--tilt", `${(target.x * 1.6).toFixed(2)}deg`);
      stage.style.setProperty("--shift-x", `${(target.x * 5).toFixed(2)}px`);
      stage.style.setProperty("--shift-y", `${(target.y * 4).toFixed(2)}px`);
    };

    stage.addEventListener("mousemove", (event) => {
      if (window.innerWidth < 901) return;
      const rect = stage.getBoundingClientRect();
      target = {
        x: (event.clientX - rect.left) / rect.width - 0.5,
        y: (event.clientY - rect.top) / rect.height - 0.5,
      };
      if (!frameId) frameId = window.requestAnimationFrame(apply);
    });

    stage.addEventListener("mouseleave", () => {
      target = { x: 0, y: 0 };
      if (!frameId) frameId = window.requestAnimationFrame(apply);
    });
  }
})();
