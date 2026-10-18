/* DD 监控室 CE — prototype interactions
   Kept dependency-free so the prototype can be opened as a file.
   ?capture=1 freezes decorative motion for the review screenshot. */

(() => {
  const root = document.documentElement;
  const params = new URLSearchParams(window.location.search);
  const capture = params.has("capture");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (capture) {
    root.classList.add("capture");
  }

  /* ---------- layout mode preview ---------- */

  const modes = {
    split: {
      label: "横屏 · 平分布局",
      code: "01",
      tag: "平分 / LANDSCAPE",
      caption: "当前：横屏 · 平分布局",
      src: "assets/wall-landscape.jpg",
      alt: "DD监控室 CE 横屏平分布局截图",
      portrait: false,
    },
    hero: {
      label: "横屏 · 大带小",
      code: "02",
      tag: "大带小 / LANDSCAPE",
      caption: "当前：横屏 · 大带小",
      src: "assets/wall-landscape.jpg",
      alt: "DD监控室 CE 横屏大带小布局截图",
      portrait: false,
    },
    danmaku: {
      label: "横屏 · 弹幕布局",
      code: "03",
      tag: "弹幕 / LANDSCAPE",
      caption: "当前：横屏 · 弹幕布局",
      src: "assets/wall-danmaku.jpg",
      alt: "DD监控室 CE 弹幕布局截图",
      portrait: false,
    },
    portrait: {
      label: "竖屏 · 主画面铺满",
      code: "04",
      tag: "竖屏 / PORTRAIT",
      caption: "当前：竖屏 · 主画面铺满",
      src: "assets/wall-portrait.jpg",
      alt: "DD监控室 CE 竖屏布局截图",
      portrait: true,
    },
  };

  const modeButtons = [...document.querySelectorAll("[data-mode]")];
  const modeRows = [...document.querySelectorAll("[data-mode-row]")];
  const layoutImage = document.getElementById("layout-image");
  const layoutShot = document.getElementById("layout-shot");
  const layoutLabel = document.getElementById("layout-label");
  const layoutCode = document.getElementById("layout-code");
  const layoutTag = document.getElementById("layout-tag");
  const layoutCaption = document.getElementById("layout-caption");

  const selectMode = (name) => {
    const mode = modes[name];
    if (!mode || !layoutImage) return;

    modeButtons.forEach((button) => {
      const active = button.dataset.mode === name;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    modeRows.forEach((row) => {
      row.classList.toggle("is-active", row.dataset.modeRow === name);
    });

    layoutImage.src = mode.src;
    layoutImage.alt = mode.alt;
    layoutLabel.textContent = mode.label;
    layoutCode.textContent = mode.code;
    layoutTag.textContent = mode.tag;
    layoutCaption.textContent = mode.caption;
    layoutShot.classList.toggle("is-portrait", mode.portrait);
  };

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => selectMode(button.dataset.mode));
  });

  const startMode = params.get("mode");
  if (startMode && modes[startMode]) selectMode(startMode);

  /* ---------- console micro-states ---------- */

  document.querySelectorAll(".route").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      button.classList.toggle("is-on");
    });
  });

  document.querySelectorAll(".rec-btn").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      const active = button.classList.toggle("is-rec");
      button.lastChild.textContent = active ? "停止" : "录制";
    });
  });

  const saveButton = document.querySelector(".rec-save");
  if (saveButton) {
    saveButton.addEventListener("click", () => {
      const original = saveButton.textContent;
      saveButton.textContent = "已加入导出 ✓";
      saveButton.disabled = true;
      window.setTimeout(() => {
        saveButton.textContent = original;
        saveButton.disabled = false;
      }, 1800);
    });
  }

  /* ---------- pointer parallax on the monitor wall ---------- */

  const wall = document.getElementById("hero-wall");
  const visual = document.querySelector(".hero-visual");

  if (wall && visual && !capture && !reduceMotion) {
    let frame = 0;
    let target = { x: 0, y: 0 };

    const apply = () => {
      frame = 0;
      wall.style.setProperty("--ry", `${(-3.2 + target.x * 2.4).toFixed(2)}deg`);
      wall.style.setProperty("--rx", `${(1.2 - target.y * 1.8).toFixed(2)}deg`);
    };

    visual.addEventListener("mousemove", (event) => {
      if (window.innerWidth < 861) return;
      const rect = visual.getBoundingClientRect();
      target = {
        x: (event.clientX - rect.left) / rect.width - 0.5,
        y: (event.clientY - rect.top) / rect.height - 0.5,
      };
      if (!frame) frame = window.requestAnimationFrame(apply);
    });

    visual.addEventListener("mouseleave", () => {
      target = { x: 0, y: 0 };
      if (!frame) frame = window.requestAnimationFrame(apply);
    });
  }

  /* ---------- entrance state ---------- */
  root.classList.add("is-ready");
})();
