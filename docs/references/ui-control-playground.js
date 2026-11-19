// The order matches the rows of ui-control-library-qt.png.
const labControls = [
  ['collapse', '全部展开后的收起方式', '常规 › 关注与预览', 170, 34, 18,
    '收起全部关注文件夹，或恢复本次全部展开前的状态。'],
  ['interval', '关注列表刷新间隔', '常规 › 关注与预览', 178, 32, 8,
    '用加减按钮或数字输入调整轮询间隔，范围为 1–30 分钟。'],
  ['preview', '关注栏直播预览', '常规 › 关注与预览', 46, 23, 14,
    '开启后，在关注栏的直播间上悬停会显示播放预览。'],
  ['initial-volume', '新建格子的初始音量', '常规 › 播放与声音', 214, 28, 6,
    '设置新建播放格使用的默认音量。'],
  ['codec', '直播源格式', '常规 › 编解码', 188, 34, 18,
    '选择直播流编码偏好，可选 H.264、HEVC 和 AV1。'],
  ['decoder', '本机解码方式', '常规 › 编解码', 200, 32, 8,
    '选择本机处理视频的方式，自动解码会优先使用可用的硬件。'],
  ['theme', '界面主题', '外观 › 主题', 238, 34, 18,
    '切换深色、浅色或跟随系统，此处会同步改变图鉴的预览主题。'],
  ['palette', '主题色', '外观 › 主题', 207, 28, 14,
    '在默认主题色与预设颜色间切换，详情可直接调任意强调色。'],
  ['pause', '暂停／继续', '底部信息条', 32, 28, 8,
    '切换当前播放格的暂停状态，再点一次继续。'],
  ['volume', '格子音量', '底部信息条 · 宽格子', 172, 28, 7,
    '点击扬声器静音或取消静音，也可以拖动滑块独立调整音量。'],
  ['danmaku', '画面弹幕／观看设置', '底部信息条', 71, 28, 7,
    '左侧开关控制画面弹幕，齿轮打开弹幕观看设置。'],
  ['record', '录制', '底部信息条', 76, 28, 7,
    '在开始和停止录制之间切换，浏览器样例会显示当前状态。'],
  ['fullscreen', '全屏', '底部信息条', 32, 28, 7,
    '切换进入与退出全屏的按钮状态。'],
  ['quality', '画质', '悬停时 · 右上角', 102, 28, 8,
    '选择单路直播的画质。直播中的可选档位由平台提供。'],
  ['reconnect', '重新连接', '悬停时 · 右上角', 32, 28, 8,
    '重新连接这一路，试用区会依次呈现连接中与已连接。'],
  ['close', '关闭这一路', '悬停时 · 右上角', 32, 28, 8,
    '关闭当前播放格。试用区可再次点击恢复样例。'],
].map(([id, title, location, width, height, radius, usage], row) => ({
  id, title, location, width, height, radius, usage, row,
  source: row < 6 ? 'ddm/settings_general.py' : row < 8 ? 'ddm/settings_appearance.py' : 'ddm/tile_widgets.py',
}));

const labPresets = [['', '默认'], ['#00a1d6', '蓝'], ['#20b976', '绿'], ['#8866ee', '紫'],
  ['#ef638e', '粉'], ['#f58b32', '橙']];
const labTransitions = {
  pause: [['pause', '', '播放中'], ['play', '', '已暂停']],
  volume: [['volume', '', '声音已开启'], ['mute', '', '已静音']],
  danmaku: [['chat', '弹', '画面弹幕已关闭'], ['check', '弹', '画面弹幕已开启']],
  record: [['circle', '录制', '已停止录制'], ['circle', '停止', '正在录制']],
  fullscreen: [['fullscreen', '', '已退出全屏'], ['minimize', '', '已进入全屏']],
  close: [['close', '', '已恢复播放格'], ['plus', '', '已关闭，点击可恢复']],
};

const labButton = (label, glyph = '', text = '', attrs = '', primary = false) =>
  `<button type="button" class="lab-control ${text ? '' : 'lab-icon-only'}" aria-label="${label}" title="${label}" ${attrs} ${primary ? 'data-primary' : ''}>
    <span class="lab-glyph" ${primary ? 'data-icon-slot' : ''}>${glyph ? icon(glyph) : ''}</span><span class="lab-label">${text}</span>
  </button>`;

const labFlip = (id, label, active = false) => {
  const [glyph, text] = labTransitions[id][Number(active)];
  return labButton(label, glyph, text, `data-lab-toggle="${id}" aria-pressed="${active}"`, true);
};

const labSelect = (label, values) => `<select class="lab-control lab-select" aria-label="${label}" data-primary>
  ${values.map(value => `<option>${value}</option>`).join('')}
</select>`;

const labChoice = (label, values) => `<div class="lab-choice" role="group" aria-label="${label}">
  ${values.map(([value, text], index) => labButton(text, '', text,
    `data-lab-choice="${value}" aria-pressed="${index === 0}"`, index === 0)).join('')}
</div>`;

const labRange = (label, min, max, value, unit = '', primary = false) =>
  `<label class="lab-range"><input type="range" aria-label="${label}" min="${min}" max="${max}" value="${value}" ${primary ? 'data-primary' : ''}>
    <output data-unit="${unit}">${value}${unit}</output></label>`;

const labDanmakuParams = [['显示区域', 10, 100, 50, '%'], ['不透明度', 10, 100, 80, '%'],
  ['字体大小', 12, 64, 28, ' px'], ['弹幕速度', 50, 200, 100, '%'], ['描边宽度', 0, 6, 0, ' px']];

function labExample({ id, title }) {
  switch (id) {
    case 'collapse': return labChoice(title, [['all', '全部收起'], ['previous', '恢复原状']]);
    case 'interval': return labButton('减少一分钟', 'minus', '', 'data-lab-step="-1"')
      + `<input class="lab-control lab-step-value" type="number" min="1" max="30" value="1" aria-label="${title}" data-primary><span class="lab-unit">分钟</span>`
      + labButton('增加一分钟', 'plus', '', 'data-lab-step="1"');
    case 'preview': return `<label class="lab-switch" data-primary><input type="checkbox" role="switch" aria-label="${title}" checked>
      <span class="lab-track" aria-hidden="true"></span></label>`;
    case 'initial-volume': return labRange(title, 0, 100, 40, '', true);
    case 'codec': return labChoice(title, [['avc', 'H.264'], ['hevc', 'HEVC'], ['av1', 'AV1']]);
    case 'decoder': return labSelect(title, ['自动解码（推荐）', '兼容硬解（回传内存）', '软件解码（CPU）',
      'D3D11VA 显卡解码', 'DXVA2 显卡解码（旧设备）']);
    case 'theme': return labChoice(title, [['dark', '深色'], ['light', '浅色'], ['system', '跟随系统']]);
    case 'palette': return `<div class="lab-swatches" role="group" aria-label="${title}">
      ${labPresets.map(([color, label], index) => `<button type="button" class="lab-control ${index ? 'lab-swatch-dot' : ''}"
        aria-label="${label}" title="${label}" aria-pressed="${index === 0}" data-lab-choice="${color}"
        ${index ? `style="--swatch:${color}"` : 'data-primary'}>${index ? '' : label}</button>`).join('')}
      </div>`;
    case 'volume': return labFlip(id, '静音／取消静音') + labRange(title, 0, 100, 40);
    case 'danmaku': return labFlip(id, '切换画面弹幕', true)
      + labButton('弹幕观看设置', 'settings', '', 'data-lab-dialog');
    case 'quality': return labSelect(title, ['原画', '蓝光', '超清 720P', '流畅']);
    case 'reconnect': return labButton(title, 'refresh', '', 'data-lab-reconnect', true);
    default: return labFlip(id, title);
  }
}

const labGallery = document.getElementById('qt-gallery');
const labOverview = document.getElementById('overview');
const labDetail = document.getElementById('playground-detail');
const labContext = document.getElementById('playground-context');
const labSystemTheme = window.matchMedia('(prefers-color-scheme: light)');
let labOpen;
let labTheme = 'dark';

function labSetTheme(mode) {
  labTheme = mode;
  const effective = mode === 'system' ? labSystemTheme.matches ? 'light' : 'dark' : mode;
  labOverview.dataset.themeMode = effective;
  labOverview.querySelectorAll('[data-qt-theme]').forEach(button =>
    button.setAttribute('aria-pressed', button.dataset.qtTheme === effective));
  labOverview.querySelectorAll('[data-lab-demo="theme"] [data-lab-choice]').forEach(button =>
    button.setAttribute('aria-pressed', button.dataset.labChoice === mode));
  labSyncColors();
}

function labMount(host, item) {
  const { id, width, height, radius } = item;
  host.dataset.labDemo = id;
  host.dataset.state = 'live';
  host.style.cssText = `--lab-width:${width}px;--lab-height:${height}px;--lab-radius:${radius}px`;
  host.innerHTML = `<fieldset aria-label="${item.title}">
    <div class="lab-main"><span class="lab-extra" aria-hidden="true" hidden></span><div class="lab-controls">${labExample(item)}</div></div>
    </fieldset><output class="lab-status" aria-live="polite"></output>
    ${id === 'danmaku' ? `<dialog class="lab-dialog" aria-label="弹幕观看设置"><h4>弹幕观看设置</h4>
      ${labDanmakuParams.map(values => `<div class="lab-range-row"><span>${values[0]}</span>${labRange(...values)}</div>`).join('')}
      <form method="dialog"><button class="lab-control">完成</button></form></dialog>` : ''}`;
  const status = host.querySelector('.lab-status');
  const number = host.querySelector('.lab-step-value');
  let iconChoice = 'default';

  function paintIcon(button, glyph) {
    button.dataset.labGlyph = glyph;
    const current = button.hasAttribute('data-primary') && iconChoice !== 'default' ? iconChoice : glyph;
    button.querySelector('.lab-glyph').innerHTML = current && current !== 'none' ? icon(current) : '';
  }

  const main = host.querySelector('button[data-primary]:has([data-icon-slot])');
  if (main) main.dataset.labGlyph = id in labTransitions
    ? labTransitions[id][Number(id === 'danmaku')][0] : id === 'reconnect' ? 'refresh' : '';

  host.setPreviewIcon = choice => {
    iconChoice = choice;
    const leading = host.querySelector('.lab-extra');
    if (main) paintIcon(main, main.dataset.labGlyph);
    leading.hidden = Boolean(main) || choice === 'default' || choice === 'none';
    leading.innerHTML = leading.hidden ? '' : icon(choice);
  };

  function setIntervalValue(value) {
    number.value = Math.min(30, Math.max(1, Math.round(value)));
    status.textContent = `刷新间隔 ${number.value} 分钟`;
    host.querySelector('[data-lab-step="-1"]').disabled = Number(number.value) <= 1;
    host.querySelector('[data-lab-step="1"]').disabled = Number(number.value) >= 30;
  }
  if (number) {
    setIntervalValue(1);
    status.textContent = '';
    number.addEventListener('change', () => setIntervalValue(Number(number.value) || 1));
  }

  host.oninput = event => {
    event.stopPropagation();
    const input = event.target;
    if (input.type === 'range') {
      const output = input.nextElementSibling;
      output.textContent = input.value + output.dataset.unit;
      status.textContent = `${input.getAttribute('aria-label')} ${output.value}`;
    } else if (input.type === 'checkbox') {
      status.textContent = input.checked ? '已开启直播预览' : '已关闭直播预览';
    } else if (input.tagName === 'SELECT') {
      status.textContent = `已选 ${input.value}`;
    }
  };

  host.onclick = event => {
    event.stopPropagation();
    const clicked = event.target.closest('button');
    if (!clicked) return;
    if (clicked.hasAttribute('data-lab-choice')) {
      host.querySelectorAll('[data-lab-choice]').forEach(button => button.setAttribute('aria-pressed', button === clicked));
      const value = clicked.dataset.labChoice;
      if (id === 'theme') labSetTheme(value);
      if (id === 'palette') {
        const surface = host.querySelector('.lab-controls');
        if (value) surface.style.setProperty('--lab-accent', value);
        else surface.style.removeProperty('--lab-accent');
      }
      status.textContent = `已选 ${clicked.getAttribute('aria-label')}`;
    } else if (clicked.dataset.labStep) {
      setIntervalValue(Number(number.value) + Number(clicked.dataset.labStep));
    } else if (clicked.dataset.labToggle) {
      const active = clicked.getAttribute('aria-pressed') !== 'true';
      const [glyph, text, feedback] = labTransitions[id][Number(active)];
      clicked.setAttribute('aria-pressed', active);
      paintIcon(clicked, glyph);
      clicked.querySelector('.lab-label').textContent = text;
      status.textContent = feedback;
    } else if (clicked.hasAttribute('data-lab-dialog')) {
      host.querySelector('dialog').showModal();
    } else if (clicked.hasAttribute('data-lab-reconnect')) {
      clicked.disabled = true;
      clicked.setAttribute('aria-busy', 'true');
      clicked.classList.add('lab-spinner');
      status.textContent = '正在连接…';
      window.setTimeout(() => {
        clicked.disabled = false;
        clicked.removeAttribute('aria-busy');
        clicked.classList.remove('lab-spinner');
        status.textContent = '已重新连接';
      }, 850);
    }
  };
}

const labPaintFields = [
  ['accent', '强调色', '--lab-accent'], ['surface', '控件底色', '--lab-surface'],
  ['ink', '文字／图标色', '--lab-ink'], ['hover', '悬停底色', '--lab-hover'],
];

function labSyncColors() {
  const sample = labDetail.querySelector('.lab-detail-stage');
  if (!sample) return;
  const styles = getComputedStyle(sample);
  labPaintFields.forEach(([name, , token]) => {
    const field = labDetail.querySelector(`[name="${name}"]`);
    field.value = styles.getPropertyValue(token).trim();
    field.nextElementSibling.textContent = field.value.toUpperCase();
  });
}

const labStates = [['live', '实时操作'], ['hover', '悬停'], ['pressed', '按下'], ['focus', '键盘焦点'], ['disabled', '禁用']];
const labIcons = [['default', '控件默认'], ['none', '隐藏图标'], ['settings', '齿轮'], ['check', '勾选'],
  ['volume', '扬声器'], ['pause', '暂停'], ['refresh', '刷新'], ['close', '关闭']];
const labOptions = items => items.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
const labNumberFields = item => [
  ['width', '宽度 (px)', 26, 340, item.width],
  ['height', '高度 (px)', 18, 58, item.height],
  ['radius', '圆角 (px)', 0, 30, item.radius],
  ['font', '字号 (px)', 10, 24, 13],
  ['icon-size', '图标大小 (px)', 10, 30, 15],
  ['motion', '动效时长 (ms)', 0, 500, 120],
];

function labRenderDetail(item) {
  const numbers = labNumberFields(item);
  labDetail.innerHTML = `<header class="lab-detail-head">
    <div><h2 id="playground-name" tabindex="-1">${item.title}</h2><p>${item.row < 8 ? '设置页' : '播放格'} › ${item.location}</p></div>
    <a class="lab-link" href="#overview">返回总览</a></header>
    <div class="lab-detail-layout">
      <section class="lab-panel"><h3>实时预览</h3><div class="lab-demo lab-detail-stage"></div>
        <figure class="lab-reference"><figcaption>当前 Qt 外观</figcaption>
          <div class="qt-swatch" role="img" aria-label="${item.title}的 Qt 截图" style="--qt-y:${item.row / (labControls.length - 1) * 100}%"></div></figure>
        <div class="lab-source"><p>${item.usage}</p><code>${item.source}</code></div>
      </section>
      <section class="lab-panel"><div class="lab-props-head"><h3>预览参数</h3><button type="button" class="lab-reset">重置预览</button></div>
        <form class="lab-form">
          <label class="lab-span">交互状态<select name="state">${labOptions(labStates)}</select></label>
          ${labPaintFields.map(([name, label]) => `<label>${label}<span class="lab-color-input"><input type="color" name="${name}"><output></output></span></label>`).join('')}
          ${numbers.map(([name, label, min, max, value]) =>
            `<label>${label}<input type="number" name="${name}" min="${min}" max="${max}" value="${value}"></label>`).join('')}
          <label class="lab-span">图标<select name="icon">${labOptions(labIcons)}</select></label>
        </form>
        <p class="lab-motion-note">时长为 0 时即时切换。系统「减少动态效果」始终生效。</p>
      </section>
    </div>`;
  const sample = labDetail.querySelector('.lab-detail-stage');
  const form = labDetail.querySelector('.lab-form');
  labMount(sample, item);
  labSetTheme(labTheme);
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', event => {
    const field = event.target;
    const paint = labPaintFields.find(([name]) => name === field.name);
    if (paint) {
      sample.style.setProperty(paint[2], field.value);
      field.nextElementSibling.textContent = field.value.toUpperCase();
      if (paint[0] === 'accent') sample.querySelector('.lab-controls').style.removeProperty('--lab-accent');
    } else if (field.name === 'state') {
      sample.dataset.state = field.value;
      sample.querySelector('fieldset').disabled = field.value === 'disabled';
    } else if (field.name === 'icon') {
      sample.setPreviewIcon(field.value);
    } else if (field.validity.valid && field.value !== '') {
      sample.style.setProperty(`--lab-${field.name}`, field.value + (field.name === 'motion' ? 'ms' : 'px'));
    }
  });
  labDetail.querySelector('.lab-reset').addEventListener('click', () => {
    form.reset();
    labMount(sample, item);
    labSetTheme(labTheme);
  });
}

function labShowRoute() {
  const item = labControls.find(({ id }) => location.hash === `#control-${id}`);
  const previous = labOpen;
  labOpen = item;
  labGallery.hidden = Boolean(item);
  labDetail.hidden = !item;
  labContext.textContent = item ? '网页交互试样 · 对照当前 Qt 外观' : '16 项软件在用控件 · 网页交互试样';
  if (item) {
    setTab(document.getElementById('tab-overview'));
    labRenderDetail(item);
    document.getElementById('playground-name').focus({ preventScroll: true });
    window.scrollTo(0, 0);
  } else if (previous) {
    const link = labGallery.querySelector(`[href="#control-${previous.id}"]`);
    link.focus({ preventScroll: true });
    link.scrollIntoView({ block: 'nearest' });
  }
}

labGallery.innerHTML = ['设置页', '播放格'].map((area, index) =>
  `<section class="qt-group"><h2>${area}</h2><div class="qt-grid">${labControls.slice(index * 8, index * 8 + 8).map(item =>
    `<article class="qt-card"><header><div><h3>${item.title}</h3><small>${item.location}</small></div>
      <a class="lab-link" href="#control-${item.id}" aria-label="${item.title}详情">详情</a></header>
      <div class="lab-demo" data-lab-demo="${item.id}"></div></article>`).join('')}</div></section>`).join('');
labControls.forEach(item => labMount(labGallery.querySelector(`[data-lab-demo="${item.id}"]`), item));

labOverview.querySelectorAll('[data-qt-theme]').forEach(button =>
  button.addEventListener('click', () => labSetTheme(button.dataset.qtTheme)));
labSystemTheme.addEventListener('change', () => {
  if (labTheme === 'system') labSetTheme(labTheme);
});
window.addEventListener('hashchange', labShowRoute);
labShowRoute();
