// The order matches the rows of ui-control-library-qt.png.
const labControls = [
  ['collapse', '全部展开后的收起方式', '常规 › 关注与预览', 320, 34, 18,
    '收起全部关注文件夹，或恢复本次全部展开前的状态。'],
  ['interval', '关注列表刷新间隔', '常规 › 关注与预览', 180, 34, 8,
    '用加减按钮或数字输入调整轮询间隔，范围为 1–30 分钟。'],
  ['preview', '关注栏直播预览', '常规 › 关注与预览', 44, 26, 13,
    '开启后，在关注栏的直播间上悬停会显示播放预览。'],
  ['initial-volume', '新建格子的初始音量', '常规 › 播放与声音', 214, 28, 6,
    '设置新建播放格使用的默认音量。'],
  ['codec', '直播源格式', '常规 › 编解码', 320, 34, 18,
    '选择直播流编码偏好，可选 H.264、HEVC 和 AV1。'],
  ['decoder', '本机解码方式', '常规 › 编解码', 209, 34, 8,
    '选择本机处理视频的方式，自动解码会优先使用可用的硬件。'],
  ['theme', '界面主题', '外观 › 主题', 320, 34, 17,
    '切换深色、浅色或跟随系统，此处会同步改变图鉴的预览主题。'],
  ['palette', '主题色', '外观 › 主题', 201, 28, 8,
    '在默认主题色与预设颜色间切换，详情可直接调任意强调色。'],
  ['pause', '暂停／继续', '底部信息条', 34, 26, 13,
    '切换当前播放格的暂停状态，再点一次继续。'],
  ['volume', '格子音量', '底部信息条 · 宽格子', 166, 26, 13,
    '点击扬声器静音或取消静音，也可以拖动滑块独立调整音量。'],
  ['danmaku', '画面弹幕／观看设置', '底部信息条', 68, 26, 13,
    '左侧开关控制画面弹幕，齿轮打开弹幕观看设置。'],
  ['record', '录制', '底部信息条', 64, 26, 13,
    '在开始和停止录制之间切换，浏览器样例会显示当前状态。'],
  ['fullscreen', '全屏', '底部信息条', 28, 26, 13,
    '切换进入与退出全屏的按钮状态。'],
  ['quality', '画质', '悬停时 · 右上角', 40, 26, 13,
    '选择单路直播的画质。直播中的可选档位由平台提供。'],
  ['reconnect', '重新连接', '悬停时 · 右上角', 32, 26, 13,
    '重新连接这一路，试用区会依次呈现连接中与已连接。'],
  ['close', '关闭这一路', '悬停时 · 右上角', 26, 26, 13,
    '关闭当前播放格。试用区可再次点击恢复样例。'],
].map(([id, title, location, width, height, radius, usage], row) => ({
  id, title, location, width, height, radius, usage, row,
  group: row < 8 ? '设置页' : '播放格',
  area: row < 8 ? 'settings' : row < 13 ? 'bottom' : 'overlay',
  source: row < 6 ? 'ddm/settings_general.py' : row < 8 ? 'ddm/settings_appearance.py' : 'ddm/tile_widgets.py',
})).concat(labAdditionalControls, labApplicationControls);

const labPresets = [['', '默认'], ['#00a1d6', '蓝'], ['#20b976', '绿'], ['#8866ee', '紫'],
  ['#ef638e', '粉'], ['#f58b32', '橙']];
const labTileGlyphs = {
  'qt-pause': '<rect x="5" y="4" width="5" height="16" rx="1.7" fill="currentColor"/><rect x="14" y="4" width="5" height="16" rx="1.7" fill="currentColor"/>',
  'qt-volume': '<path d="M2 10h4l5-4v12l-5-4H2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><text x="14.5" y="14.8" fill="var(--lab-accent)" font-weight="700" font-size="7.5">LR</text>',
  'qt-mute': '<path d="M2 10h4l5-4v12l-5-4H2zm13-1 6 6m0-6-6 6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>',
  'qt-reconnect': '<path d="M4 12A8 8 0 0 1 17 6m3 6a8 8 0 0 1-13 6" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m15 2 5 6-8-1zm-6 20-5-6 8 1z" fill="currentColor"/>',
};
const labQtGlyphs = {
  'qt-grid': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  'qt-tabs': '<rect x="3" y="8" width="17" height="12" rx="2"/><path d="M6 5h11m-7 6 5 3-5 3z"/>',
  'qt-live': '<path d="M7 8a6 6 0 0 0 0 8m10-8a6 6 0 0 1 0 8M4 5a10 10 0 0 0 0 14m16-14a10 10 0 0 1 0 14"/><circle cx="12" cy="12" r="2.5" fill="#fb7299" stroke="none"/>',
  'qt-check-stack': '<rect x="4" y="7" width="13" height="13" rx="2"/><path d="m7 13 2 2 4-5M8 4h10a2 2 0 0 1 2 2v10"/>',
  'qt-swap': '<path d="M3 8h17l-4-4m5 12H4l4 4"/>',
  'qt-return': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M15 12H8m4-4-4 4 4 4"/>',
  'qt-caption': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10h10m-10 4h7"/>',
  'qt-lock': '<rect x="6" y="10" width="12" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  'qt-bili': '<rect x="3.5" y="8" width="17" height="12" rx="2.5"/><path d="m8 8-2-4m10 4 2-4m-9 9v2m6-2v2"/>',
  'qt-image': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 16 5-5 8 9m-2-5 4-4 3 3"/><circle cx="15" cy="8" r="1"/>',
  'qt-image-off': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 3 18 18"/>',
  'qt-trash': '<path d="M4 7h16m-13 0 1 13h8l1-13M9 7V4h6v3m-5 3v6m4-6v6"/>',
  star: '<path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.3-5.7-3-5.7 3 1.1-6.3-4.6-4.5 6.4-.9z"/>',
  heart: '<path d="M12 21 3.5 12.5C-2 6 7 0 12 7c5-7 14-1 8.5 5.5z"/>',
  game: '<path d="M7 7h10c3 0 4 3 5 10 0 3-3 3-5 0l-2-2H9l-2 2c-2 3-5 3-5 0 1-7 2-10 5-10zM6 10v5m-2.5-2.5h5M17 11h.01M19 14h.01"/>',
  music: '<path d="M9 17V5l11-2v12M9 9l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
};
const labPlatformIcons = {
  'platform-bili': 'bilibili.ico', 'platform-huya': 'huya.png', 'platform-douyu': 'douyu.ico',
};
const labIcon = glyph => labPlatformIcons[glyph]
  ? `<img src="../../assets/platforms/${labPlatformIcons[glyph]}" alt="">`
  : labTileGlyphs[glyph]
  ? `<svg viewBox="0 0 24 24" aria-hidden="true">${labTileGlyphs[glyph]}</svg>`
  : labQtGlyphs[glyph]
    ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${labQtGlyphs[glyph]}</svg>`
    : icon(glyph);
const labTransitions = {
  pause: [['qt-pause', '', '播放中'], ['play', '', '已暂停']],
  volume: [['qt-volume', '', '声音已开启'], ['qt-mute', '', '已静音']],
  danmaku: [['', '弹', '画面弹幕已关闭'], ['', '弹', '画面弹幕已开启']],
  record: [['', '● 录制', '已停止录制'], ['', '● REC', '正在录制']],
  fullscreen: [['fullscreen', '', '已退出全屏'], ['fullscreen', '', '已进入全屏']],
  close: [['close', '', '已恢复播放格'], ['plus', '', '已关闭，点击可恢复']],
};

const labButton = (label, glyph = '', text = '', attrs = '', primary = false) =>
  `<button type="button" class="lab-control ${text ? '' : 'lab-icon-only'}" aria-label="${label}" title="${label}" ${attrs} ${primary ? `data-primary data-lab-glyph="${glyph}"` : ''}>
    <span class="lab-glyph" ${primary ? 'data-icon-slot' : ''}>${glyph ? labIcon(glyph) : ''}</span><span class="lab-label">${text}</span>
  </button>`;

const labFlip = (id, label, active = false) => {
  const [glyph, text] = labTransitions[id][Number(active)];
  return labButton(label, glyph, text, `data-lab-toggle="${id}" aria-pressed="${active}"`, true);
};

const labSelect = (label, values) => `<select class="lab-control lab-select" aria-label="${label}" data-primary>
  ${values.map(value => `<option>${value}</option>`).join('')}
</select>`;

const labChoice = (label, values) => `<div class="lab-choice" role="group" aria-label="${label}" style="--lab-choice-count:${values.length}">
  ${values.map(([value, text], index) => labButton(text, '', text,
    `data-lab-choice="${value}" aria-pressed="${index === 0}"`, index === 0)).join('')}
  <span class="lab-choice-indicator" aria-hidden="true"></span>
</div>`;

const labRange = (label, min, max, value, unit = '', primary = false) =>
  `<label class="lab-range"><input type="range" aria-label="${label}" min="${min}" max="${max}" value="${value}" style="--lab-level:${(value - min) * 100 / (max - min)}%" ${primary ? 'data-primary' : ''}>
    <output data-unit="${unit}">${value}${unit}</output></label>`;

const labDanmakuParams = [['显示区域', 10, 100, 50, '%'], ['不透明度', 10, 100, 80, '%'],
  ['字体大小', 12, 64, 28, ' px'], ['弹幕速度', 50, 200, 100, '%'], ['描边宽度', 0, 6, 0, ' px']];

function labExample({ id, title }, popupId) {
  switch (id) {
    case 'collapse': return labChoice(title, [['all', '全部收起'], ['previous', '恢复原状']]);
    case 'interval': return labButton('减少一分钟', 'minus', '', 'data-lab-step="-1"')
      + `<label class="lab-step-field"><input class="lab-control lab-step-value" type="number" min="1" max="30" value="1" aria-label="${title}" data-primary><span>分钟</span></label>`
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
      + labButton('弹幕观看设置', 'settings', '', `popovertarget="${popupId}"`);
    case 'quality': return labSelect(title, ['原画', '蓝光', '超清 720P', '流畅']);
    case 'reconnect': return labButton(title, 'qt-reconnect', '', 'data-lab-reconnect', true);
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

function labSetTheme(mode, slidingGroup = null) {
  labTheme = mode;
  const effective = mode === 'system' ? labSystemTheme.matches ? 'light' : 'dark' : mode;
  labOverview.dataset.themeMode = effective;
  labOverview.querySelectorAll('[data-qt-theme]').forEach(button =>
    button.setAttribute('aria-pressed', button.dataset.qtTheme === effective));
  labOverview.querySelectorAll('[data-lab-demo="theme"] .lab-choice').forEach(group =>
    gallerySelectSegment(group, group.querySelector(`[data-lab-choice="${mode}"]`), group === slidingGroup));
  labSyncColors();
}

function labMount(host, item) {
  const { id, width, height, radius } = item;
  host.dataset.labDemo = id;
  host.dataset.labArea = item.area;
  host.dataset.state = 'live';
  delete host.dataset.customRadius;
  host.style.cssText = `--lab-width:${width}px;--lab-height:${height}px;--lab-radius:${radius}px`;
  const popupId = `lab-${id}-${host.classList.contains('lab-detail-stage') ? 'detail' : 'card'}`;
  const content = item.sheet === 'application' ? labAppExample(item, popupId)
    : item.sheet === 'extra' ? labAdditionalExample(item, popupId) : labExample(item, popupId);
  host.innerHTML = `<fieldset aria-label="${item.title}">
    <div class="lab-main"><span class="lab-extra" aria-hidden="true" hidden></span><div class="lab-controls">${content}</div></div>
    </fieldset><output class="lab-status" aria-live="polite"></output>
    ${id === 'danmaku' ? `<div id="${popupId}" popover class="lab-danmaku-popup" role="group" aria-label="弹幕观看设置">
      ${labDanmakuParams.map(values => `<div class="lab-range-row"><span>${values[0]}</span>${labRange(...values)}</div>`).join('')}
      <div class="lab-range-row"><span>弹幕颜色</span><label class="lab-control lab-danmaku-color"><input type="color" value="#ffffff" aria-label="弹幕颜色"><output>#FFFFFF</output></label></div>
      <label class="lab-danmaku-check"><input type="checkbox" checked>弹幕随屏幕缩放</label>
      <label class="lab-danmaku-check"><input type="checkbox">独立调整此格弹幕</label>
      <button class="lab-control lab-danmaku-more" type="button" popovertarget="${popupId}" popovertargetaction="hide" data-lab-more>更多弹幕设置</button>
    </div>` : ''}`;
  const fieldset = host.querySelector('fieldset');
  if (!fieldset.querySelector('[data-primary]')) {
    const first = fieldset.querySelector('button, input, select, textarea, [tabindex]');
    (first?.closest('.lab-switch') || first)?.setAttribute('data-primary','');
  }
  const status = host.querySelector('.lab-status');
  const number = host.querySelector('.lab-step-value');
  const report = message => { status.textContent = message; };
  if (item.sheet === 'extra') labBindAdditional(host, item, report);
  let iconChoice = 'default';

  function paintIcon(button, glyph) {
    button.dataset.labGlyph = glyph;
    const current = button.hasAttribute('data-primary') && iconChoice !== 'default' ? iconChoice : glyph;
    button.querySelector('.lab-glyph').innerHTML = current && current !== 'none' ? labIcon(current) : '';
  }
  if (item.sheet === 'application') labBindApplication(host, item, report, paintIcon);

  const main = host.querySelector('button[data-primary]:has([data-icon-slot])');
  if (main) main.dataset.labGlyph = id in labTransitions
    ? labTransitions[id][Number(id === 'danmaku')][0] : id === 'reconnect' ? 'qt-reconnect'
      : main.dataset.labGlyph || '';

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
    if (item.sheet) return;
    if (input.type === 'range') {
      const output = input.nextElementSibling;
      input.style.setProperty('--lab-level', `${(input.value - input.min) * 100 / (input.max - input.min)}%`);
      output.textContent = input.value + output.dataset.unit;
      if (id === 'volume') {
        if (Number(input.value) > 0) main.setAttribute('aria-pressed', 'false');
        paintIcon(main, labTransitions.volume[Number(input.value) === 0 ? 1 : 0][0]);
      }
      status.textContent = `${input.getAttribute('aria-label')} ${output.value}`;
    } else if (input.type === 'checkbox') {
      const label = input.getAttribute('aria-label') || input.parentElement.textContent.trim();
      status.textContent = (input.checked ? '已开启' : '已关闭') + label;
    } else if (input.type === 'color') {
      input.nextElementSibling.textContent = input.value.toUpperCase();
      status.textContent = '弹幕颜色 ' + input.value.toUpperCase();
    } else if (input.tagName === 'SELECT') {
      status.textContent = `已选 ${input.value}`;
    }
  };

  host.onkeydown = event => {
    const group = event.target.closest('.lab-choice');
    if (!group || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
    const buttons = [...group.querySelectorAll('button:enabled')];
    const index = buttons.indexOf(event.target);
    if (index === -1) return;
    event.preventDefault();
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = buttons[(index + offset + buttons.length) % buttons.length];
    next.focus();
    next.click();
  };

  function selectChoice(clicked, pointer) {
    const value = clicked.dataset.labChoice;
    const group = clicked.closest('.lab-choice');
    if (id === 'theme') labSetTheme(value, pointer ? group : null);
    else if (group) gallerySelectSegment(group, clicked, pointer);
    if (id === 'palette') {
      host.querySelectorAll('[data-lab-choice]').forEach(button => button.setAttribute('aria-pressed', button === clicked));
      const surface = host.querySelector('.lab-controls');
      if (value) surface.style.setProperty('--lab-accent', value);
      else surface.style.removeProperty('--lab-accent');
    }
    status.textContent = `已选 ${clicked.getAttribute('aria-label')}`;
  }

  fieldset.querySelectorAll('.lab-choice').forEach(group => {
    galleryBindSegment(group, '[data-lab-choice]', group.querySelector('.lab-choice-indicator'), selectChoice);
  });

  host.onclick = event => {
    event.stopPropagation();
    const clicked = event.target.closest('button');
    if (!clicked) return;
    if (clicked.hasAttribute('data-lab-choice')) {
      selectChoice(clicked, event.detail > 0);
    } else if (clicked.dataset.labStep) {
      setIntervalValue(Number(number.value) + Number(clicked.dataset.labStep));
    } else if (clicked.dataset.labToggle) {
      const active = clicked.getAttribute('aria-pressed') !== 'true';
      const [glyph, text, feedback] = labTransitions[id][Number(active)];
      clicked.setAttribute('aria-pressed', active);
      const silent = id === 'volume' && Number(host.querySelector('input').value) === 0;
      paintIcon(clicked, silent ? 'qt-mute' : glyph);
      clicked.querySelector('.lab-label').textContent = text;
      status.textContent = feedback;
    } else if (clicked.hasAttribute('data-lab-more')) {
      status.textContent = '已触发更多弹幕设置';
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
const labExtraSurface = {
  collapse: '--lab-segment', codec: '--lab-segment', theme: '--lab-segment', 'settings-material': '--lab-segment',
  decoder: '--lab-picker-bg', quality: '--lab-menu', danmaku: '--lab-menu',
  'initial-volume': '--lab-track-bg', volume: '--lab-track-bg', 'pip-audio': '--lab-audio-button-bg',
};

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
const labSegmentIds = ['collapse', 'codec', 'theme', 'settings-material'];
const labNumberFields = item => [
  ['width', '宽度 (px)', 26, 340, item.width],
  ['height', '高度 (px)', 18, 58, item.height],
  ['radius', '圆角 (px)', 0, 30, item.radius],
  ['font', '字号 (px)', 10, 24, 13],
  ['icon-size', '图标大小 (px)', 10, 30, item.id === 'volume' ? 20 : 15],
  ...(labSegmentIds.includes(item.id) ? [
    ['duration', '弹簧响应时长（秒）', 0, 2, gallerySpringDefaults.duration, 0.01],
    ['bounce', '弹性（bounce）', 0, 0.9, gallerySpringDefaults.bounce, 0.01],
  ] : [['motion', '动效时长 (ms)', 0, 500, 120]]),
];

function labRenderDetail(item) {
  const numbers = labNumberFields(item);
  const lastRow = labControls.filter(control => control.sheet === item.sheet).length - 1;
  labDetail.innerHTML = `<header class="lab-detail-head">
    <div><h2 id="playground-name" tabindex="-1">${item.title}</h2><p>${item.group} › ${item.location}</p></div>
    <a class="lab-link" href="#overview">返回总览</a></header>
    <div class="lab-detail-layout">
      <section class="lab-panel"><h3>实时预览</h3><div class="lab-demo lab-detail-stage"></div>
        <figure class="lab-reference"><figcaption>当前 Qt 外观</figcaption>
          <div class="qt-swatch" data-sheet="${item.sheet || 'base'}" role="img" aria-label="${item.title}的 Qt 截图" style="--qt-y:${item.row / lastRow * 100}%"></div></figure>
        <div class="lab-source"><p>${item.usage}</p><code>${item.source}</code></div>
      </section>
      <section class="lab-panel"><div class="lab-props-head"><h3>预览参数</h3><button type="button" class="lab-reset">重置预览</button></div>
        <form class="lab-form">
          <label class="lab-span">交互状态<select name="state">${labOptions(labStates)}</select></label>
          ${labPaintFields.map(([name, label]) => `<label>${label}<span class="lab-color-input"><input type="color" name="${name}"><output></output></span></label>`).join('')}
          ${numbers.map(([name, label, min, max, value, step = 1]) =>
            `<label>${label}<input type="number" name="${name}" min="${min}" max="${max}" step="${step}" value="${value}"></label>`).join('')}
          <label class="lab-span">图标<select name="icon">${labOptions(labIcons)}</select></label>
        </form>
        <p class="lab-motion-note">时长为 0 时即时切换。系统「减少动态效果」始终生效。</p>
        ${labSegmentIds.includes(item.id) ? '<p class="lab-motion-note">开启页顶开关后，可连续点选或水平拖动底片。</p>' : ''}
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
      if (paint[0] === 'accent') {
        sample.querySelector('.lab-controls').style.removeProperty('--lab-accent');
        sample.style.setProperty('--lab-tile-focus',field.value);
      }
      if (paint[0] === 'ink') {
        sample.style.setProperty('--lab-tile-hover-ink', field.value);
        sample.style.setProperty('--lab-choice-custom-ink', field.value);
      }
      if (paint[0] === 'surface' && labExtraSurface[item.id]) sample.style.setProperty(labExtraSurface[item.id], field.value);
    } else if (field.name === 'state') {
      sample.dataset.state = field.value;
      const fieldset = sample.querySelector('fieldset');
      fieldset.disabled = field.value === 'disabled';
      fieldset.inert = fieldset.disabled;
    } else if (field.name === 'icon') {
      sample.setPreviewIcon(field.value);
    } else if (field.validity.valid && field.value !== '') {
      if (field.name === 'duration' || field.name === 'bounce') {
        const { motion, index, settings } = gallerySegments.get(sample.querySelector('.lab-choice'));
        settings[field.name] = field.valueAsNumber;
        if (settings.duration === 0) motion.place(index());
      } else {
        sample.style.setProperty(`--lab-${field.name}`, field.value + (field.name === 'motion' ? 'ms' : 'px'));
        if (field.name === 'radius') sample.dataset.customRadius = '';
      }
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
  labContext.textContent = item ? '网页交互试样 · 对照当前 Qt 外观' : `${labControls.length} 项软件在用控件与组合`;
  labOverview.querySelector('.lab-group-links').hidden = Boolean(item);
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

const labGroups = [...new Set(labControls.map(item => item.group))];
labOverview.querySelector('.lab-group-links').innerHTML = labGroups.map((area, index) =>
  `<a class="lab-link" href="#lab-group-${index}">${area}</a>`).join('');
labGallery.innerHTML = labGroups.map((area, index) =>
  `<section class="qt-group" id="lab-group-${index}"><h2>${area}</h2><div class="qt-grid">${labControls.filter(item => item.group === area).map(item =>
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
