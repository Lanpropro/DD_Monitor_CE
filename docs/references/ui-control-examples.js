// Captures are ordered as the rows in ui-control-library-qt-extra.png.
const labAdditionalControls = [
  ['cache-action', '刷新统计', '数据与存储 › 图片缓存', 100, 34, 17, 'ddm/cache_settings.py', '模拟重新统计缓存用量，并显示结果和本次耗时。'],
  ['update-progress', '下载进度', '软件更新 › 下载', 192, 32, 4, 'ddm/update_progress_ui.py', '拖动示例控制条可查看进度条在不同数值下的绘制。'],
  ['plugin-disclosure', '插件详情展开条', '插件 › 插件商店', 90, 34, 8, 'ddm/plugin_store_ui.py', '展开插件卡片的说明和作者信息。'],
  ['danmaku-font', '弹幕字体', '弹幕 › 弹幕字体与记录', 180, 34, 8, 'ddm/settings_danmaku.py', '输入字体名称后选择。试样使用几种 Windows 本地字体。'],
  ['danmaku-color', '弹幕颜色', '播放格 › 弹幕观看设置', 188, 34, 17, 'ddm/ui/color_dialog.py', '选择预设色，或用 RGB 和 HEX 微调，确认后应用。'],
  ['scale-curve', '弹幕缩放曲线', '弹幕 › 画面弹幕缩放', 300, 34, 8, 'ddm/ui/scale_curve.py', '悬停或拖动节点可查看高度和比例。720 px 对应 100%，保持固定。'],
  ['plugin-tabs', '插件页签', '插件 › 已安装／插件商店', 175, 34, 17, 'ddm/settings_plugins.py', '在已安装与插件商店之间切换。'],
  ['settings-nav', '设置分类与页头', '设置 › 左侧分类', 246, 30, 8, 'ddm/settings_navigation.py', '切换分类，查看页面标题、说明和分组面板。'],
  ['sidebar-toggle', '收起／展开关注栏', '关注栏 › 顶部', 30, 26, 8, 'ddm/sidebar_widgets.py', '横屏下点击在「«」和「»」之间切换。'],
  ['sidebar-filter', '关注直播筛选', '关注栏 › 全部／直播中', 74, 34, 9, 'ddm/sidebar_navigation.py', '切换全部直播间与直播中的关注项。'],
  ['sidebar-multi', '多选管理按钮', '竖屏关注栏 › 工具栏', 26, 22, 11, 'ddm/sidebar_widgets.py', '在横栏中开始或结束多选管理。'],
  ['avatar-strip', '关注头像条', '竖屏关注栏 › 收起后的头像条', 132, 34, 17, 'ddm/avatar_widgets.py', '点头像选择示例直播间。粉点表示直播中，圆弧表示置顶。'],
  ['sidebar-menu', '关注管理菜单', '关注栏 › 关注管理', 34, 34, 9, 'ddm/sidebar_navigation.py', '打开多选、刷新、展开收起和分组排序选项。'],
  ['elided-title', '长标题省略', '插件商店 › 插件名称', 140, 30, 8, 'ddm/plugin_store_ui.py', '悬停查看完整标题，调整预览宽度可观察省略。'],
].map(([id, title, location, width, height, radius, source, usage], row) => ({
  id, title, location, width, height, radius, source, usage, row, sheet: 'extra',
  group: row < 8 ? '设置与工具' : '关注与导航', area: 'settings',
}));

const labFontOptions = [
  ['Microsoft YaHei UI', '微软雅黑 weiruanyahei wryh'], ['Segoe UI', ''],
  ['SimSun', '宋体 songti st'], ['KaiTi', '楷体 kaiti kt'], ['SimHei', '黑体 heiti ht'],
];

const labDanmakuColors = [['#FFFFFF', '白色'], ['#FFCF66', '暖黄'], ['#8CE99A', '浅绿'],
  ['#73DAFF', '天蓝'], ['#C5A8FF', '淡紫'], ['#FF9AB5', '浅粉']];

const labCurveDefault = () => [0, 90, 180, 360, 540, 720, 1080, 1440]
  .map(height => [height, Math.max(10, Math.round(100 * (Math.max(1, height) / 720) ** .35))]);

const labSampleTitle = '直播源与弹幕增强插件 v1.2.0';

function labAdditionalExample(item, popupId) {
  const { id, title } = item;
  const button = (text, attrs, glyph = '') => labButton(text, glyph, text, attrs, true);
  const popup = (label, content) => `${labButton(label, 'more', '', `popovertarget="${popupId}"`, true)}
    <div id="${popupId}" class="lab-extra-popup" popover aria-label="${label}">${content}</div>`;
  const choices = (values, content = '') => `<div class="lab-extra-choices" role="group" aria-label="${title}">
    ${values.map(([label, value, glyph], index) => labButton(label, glyph, glyph ? '' : label,
      `data-extra-choice="${value}" aria-pressed="${index === 0}"`, index === 0)).join('')}</div>${content}`;
  let sample;
  switch (id) {
    case 'cache-action':
      sample = button('刷新统计', 'data-extra-refresh');
      break;
    case 'update-progress':
      sample = `<div class="lab-progress-row"><progress max="100" value="64" aria-label="下载进度"></progress><output>64%</output></div>
        <label class="lab-progress-edit">模拟进度<input type="range" min="0" max="100" value="64" data-extra-progress data-primary></label>`;
      break;
    case 'plugin-disclosure':
      sample = `${button('详情', 'aria-expanded="false" data-extra-disclosure', 'down')}
        <p class="lab-extra-copy" hidden>直播源与弹幕增强插件<br>示例作者 · v1.2.0</p>`;
      break;
    case 'danmaku-font':
      sample = `${labButton(labFontOptions[0][0], 'down', labFontOptions[0][0], `popovertarget="${popupId}" data-extra-font`, true)}
        <div id="${popupId}" class="lab-extra-popup lab-font-popup" popover aria-label="弹幕字体列表">
          <input class="lab-control" type="search" placeholder="搜索字体名称" aria-label="搜索字体名称">
          ${labFontOptions.map(([name, aliases], index) => labButton(name, '', name,
            `data-extra-font-choice="${aliases}" aria-pressed="${index === 0}"`)).join('')}
          <p class="lab-extra-copy" hidden>没有匹配的字体</p>
        </div>`;
      break;
    case 'danmaku-color':
      sample = `${button('#FFFFFF', 'data-extra-color-open')}
        <dialog class="lab-color-dialog" aria-label="弹幕颜色">
          <h3>弹幕颜色</h3><p>选择预设色，或打开 RGB 色板自定义。</p>
          <div class="lab-color-preview">这是一条弹幕预览</div>
          <div class="lab-color-presets" role="group" aria-label="预设色"><span aria-hidden="true">预设色</span>
            <div class="lab-swatches">${labDanmakuColors.map(([color, label]) => `<button type="button"
              class="lab-control lab-swatch-dot" style="--swatch:${color}" data-extra-color-preset="${color}"
              aria-label="${label}" title="${label} ${color}" aria-pressed="false"></button>`).join('')}
              <button type="button" class="lab-control lab-swatch-dot lab-color-custom" data-extra-color-board-toggle
                aria-expanded="false" aria-controls="${popupId}-rgb" aria-label="自定义 RGB 色板" title="自定义 RGB 色板"></button>
            </div>
          </div>
          ${labColorBoard(popupId + '-rgb')}
          ${labColorFields()}
          <div class="lab-color-actions">${labButton('取消', '', '取消', 'data-extra-cancel data-dialog-action="cancel"')}
            ${labButton('确定', '', '确定', 'data-extra-apply data-dialog-action="confirm"')}</div>
        </dialog>`;
      break;
    case 'scale-curve':
      sample = `<svg class="lab-curve-graph" viewBox="0 -15 272 141" aria-label="画面高度与相对大小">
        <rect x="31" y="7" width="224" height="96" rx="3"></rect>
        <path class="lab-curve-grid" d="M31 31H255M31 79H255M87 7V103M143 7V103M199 7V103"></path>
        <path class="lab-curve-baseline" d="M31 55H255"></path>
        <path class="lab-curve-guides" aria-hidden="true" hidden></path>
        <text x="2" y="12">200%</text><text x="2" y="58">100%</text><text x="12" y="103">0%</text><text x="31" y="119">0</text>
        <text x="131" y="119">720</text><text x="224" y="119">1440 px</text>
        <text class="lab-curve-readout" x="255" y="-2" text-anchor="end" aria-hidden="true" hidden></text>
        <polyline class="lab-curve-line"></polyline>
        ${labCurveDefault().map(([x], index) => `<circle data-extra-point="${index}" r="4"
          ${x === 720 ? 'class="fixed"' : 'tabindex="0" role="slider" aria-valuemin="10" aria-valuemax="200"'}
          aria-label="${x} px 比例"></circle>`).join('')}
        </svg><div class="lab-curve-footer"><output data-extra-curve-value></output>${button('重置曲线','data-extra-curve-reset')}</div>`;
      break;
    case 'plugin-tabs':
      sample = labChoice(title, [['已安装插件', '已安装'], ['浏览插件商店', '插件商店']])
        + '<p class="lab-extra-copy" data-extra-content>已安装插件</p>';
      break;
    case 'settings-nav':
      sample = `<div class="lab-mini-settings"><div class="lab-mini-nav">
        <strong>设置</strong><input class="lab-control" type="search" placeholder="搜索设置分类" aria-label="搜索设置分类" data-extra-nav-search>
        <small>基础偏好</small>${choices([['常规', '播放与声音'], ['外观', '主题']])}<small>DD监控室CE</small></div>
        <section><strong data-extra-heading>常规</strong><small data-extra-description>设置播放与声音</small><p data-extra-content>播放与声音</p></section></div>`;
      break;
    case 'sidebar-toggle':
      sample = `${labButton(title, '', '«', 'data-extra-switch aria-pressed="false"', true)}`;
      break;
    case 'sidebar-filter':
      sample = choices([['全部直播间', '全部直播间', 'qt-tabs'], ['仅显示直播中', '仅显示直播中', 'qt-live']]);
      break;
    case 'sidebar-multi':
      sample = labButton('多选直播间', 'qt-check-stack', '', 'data-extra-switch aria-pressed="false"', true);
      break;
    case 'avatar-strip':
      sample = `<div class="lab-avatar-strip" role="group" aria-label="${title}">
        ${['小岚', '阿海', '星河'].map((name, index) => `<button type="button"
          class="lab-avatar ${index === 0 ? 'lab-avatar-pinned' : ''} ${index < 2 ? 'lab-avatar-live' : ''}"
          title="${name}" aria-label="${name}" aria-pressed="false" ${index ? '' : 'data-primary'}
          data-extra-choice="${name}">${index === 2 ? `<img src="${identity}" alt="">` : name[0]}</button>`).join('')}</div>`;
      break;
    case 'sidebar-menu':
      sample = popup('关注管理', ['多选管理', '刷新关注状态', '全部展开文件夹', '全部折叠文件夹']
        .map(label => button(label, 'data-extra-menu-item')).join('') +
        '<details><summary>默认分组排序</summary>' +
        ['自定义顺序', '开播优先', '导入顺序'].map(label => button(label, 'data-extra-menu-item')).join('') + '</details>');
      break;
    default:
      sample = `<span class="lab-elided-title" tabindex="0" data-primary title="${labSampleTitle}">${labSampleTitle}</span>`;
  }
  return `<div class="lab-extended">${sample}</div>`;
}

function labColorBoard(id, content = '') {
  return `<div id="${id}" class="lab-color-board" data-extra-color-board hidden>
    <div class="lab-color-plane" data-extra-color-plane role="group" tabindex="0"
      aria-label="饱和度和亮度，用方向键调整"><span></span></div>
    <label class="lab-color-hue"><span>色相</span><input type="range" min="0" max="359" data-extra-color-hue></label>
    ${content}
  </div>`;
}

function labColorFields() {
  return `${['红 R', '绿 G', '蓝 B'].map((label, index) => `<label class="lab-extra-rgb"><span>${label}</span>
    <input type="range" min="0" max="255" value="255" data-extra-channel="${index}" aria-label="${label}">
    <input type="number" min="0" max="255" value="255" data-extra-channel="${index}" aria-label="${label} 数值">
  </label>`).join('')}
  <label class="lab-extra-rgb">HEX<input type="text" maxlength="7" aria-label="HEX 色值" data-extra-hex></label>`;
}

function labBindColorBoard(dialog, updateColor, toggle) {
  const panel = dialog.querySelector('[data-extra-color-board]');
  const plane = panel.querySelector('[data-extra-color-plane]');
  const hueInput = panel.querySelector('[data-extra-color-hue]');
  let hue = 196;
  let saturation = 0;
  let brightness = 1;

  function open(opened) {
    panel.hidden = !opened;
    toggle.setAttribute('aria-expanded', opened);
  }
  toggle.setAttribute('aria-controls', panel.id);
  toggle.setAttribute('aria-expanded', 'false');
  toggle.addEventListener('click', () => open(panel.hidden));

  function paint() {
    hueInput.value = Math.min(359, Math.round(hue));
    plane.style.setProperty('--lab-board-hue', hue);
    plane.style.setProperty('--lab-board-x', `${saturation * 100}%`);
    plane.style.setProperty('--lab-board-y', `${(1 - brightness) * 100}%`);
  }

  function fromRgb(channels) {
    const [r, g, b] = channels.map(channel => channel / 255);
    brightness = Math.max(r, g, b);
    const chroma = brightness - Math.min(r, g, b);
    saturation = brightness ? chroma / brightness : 0;
    if (chroma) {
      const sector = brightness === r ? (g - b) / chroma : brightness === g ? 2 + (b - r) / chroma : 4 + (r - g) / chroma;
      hue = (sector * 60 + 360) % 360;
    }
    paint();
  }

  function apply() {
    paint();
    const hex = [5, 3, 1].map(offset => {
      const sector = (offset + hue / 60) % 6;
      const level = brightness * (1 - saturation * Math.max(0, Math.min(sector, 4 - sector, 1)));
      return Math.round(255 * level).toString(16).padStart(2, '0');
    });
    updateColor('#' + hex.join(''), true);
  }

  function pick(event) {
    const bounds = plane.getBoundingClientRect();
    saturation = galleryClamp((event.clientX - bounds.left) / bounds.width, 0, 1);
    brightness = galleryClamp(1 - (event.clientY - bounds.top) / bounds.height, 0, 1);
    apply();
  }
  plane.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button !== 0) return;
    plane.setPointerCapture(event.pointerId);
    pick(event);
  });
  plane.addEventListener('pointermove', event => { if (plane.hasPointerCapture(event.pointerId)) pick(event); });
  plane.addEventListener('keydown', event => {
    const offset = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowDown: [0, -1], ArrowUp: [0, 1] }[event.key];
    if (!offset) return;
    event.preventDefault();
    saturation = galleryClamp(saturation + offset[0] * .02, 0, 1);
    brightness = galleryClamp(brightness + offset[1] * .02, 0, 1);
    apply();
  });
  hueInput.addEventListener('input', () => { hue = hueInput.valueAsNumber; apply(); });
  return { open, fromRgb };
}

function labBindColorFields(dialog, onColor, toggle = dialog.querySelector('[data-extra-color-board-toggle]')) {
  const hex = dialog.querySelector('[data-extra-hex]');
  const channels = [...dialog.querySelectorAll('[data-extra-channel]')];
  const board = labBindColorBoard(dialog, update, toggle);
  function update(value, fromBoard = false) {
    onColor(sync(value, fromBoard));
  }
  function sync(value, fromBoard = false) {
    value = value.toUpperCase();
    const valid = /^#[0-9A-F]{6}$/.test(value);
    hex.setAttribute('aria-invalid', !valid);
    if (!valid) return '';
    hex.value = value;
    const rgb = value.slice(1).match(/../g).map(channel => parseInt(channel, 16));
    channels.forEach(field => { field.value = rgb[Number(field.dataset.extraChannel)]; });
    if (!fromBoard) board.fromRgb(rgb);
    return value;
  }
  hex.addEventListener('input', () => update(hex.value));
  channels.forEach(field => field.addEventListener('input', () => {
    if (!field.validity.valid || field.value === '') return;
    const parts = hex.value.match(/[0-9a-f]{2}/gi) || ['ff', 'ff', 'ff'];
    const channelsHex = parts.length === 3 ? parts : ['ff', 'ff', 'ff'];
    channelsHex[Number(field.dataset.extraChannel)] = Number(field.value).toString(16).padStart(2, '0');
    update('#' + channelsHex.join(''));
  }));
  return {open: board.open, sync, update};
}

function labBindColorDialog(demo, report) {
  const dialog = demo.querySelector('dialog');
  const opener = demo.querySelector('[data-extra-color-open]');
  const confirm = dialog.querySelector('[data-extra-apply]');
  const preview = dialog.querySelector('.lab-color-preview');
  const presets = dialog.querySelectorAll('[data-extra-color-preset]');
  const editor = labBindColorFields(dialog, value => {
    confirm.disabled = !value;
    presets.forEach(preset => preset.setAttribute('aria-pressed', preset.dataset.extraColorPreset === value));
    if (value) preview.style.color = value;
  });
  let applied = '#FFFFFF';
  opener.onclick = () => { editor.update(applied); editor.open(false); dialog.showModal(); };
  presets.forEach(preset => preset.addEventListener('click', () => editor.update(preset.dataset.extraColorPreset)));
  dialog.querySelector('[data-extra-cancel]').onclick = () => dialog.close();
  confirm.onclick = () => {
    applied = dialog.querySelector('[data-extra-hex]').value;
    opener.querySelector('.lab-label').textContent = applied;
    opener.style.setProperty('--lab-dialog-color', applied);
    report('已选 ' + applied);
    dialog.close();
  };
}

function labBindCurve(demo, report) {
  const graph = demo.querySelector('svg');
  const points = [...graph.querySelectorAll('[data-extra-point]')];
  const readout = graph.querySelector('.lab-curve-readout');
  const guides = graph.querySelector('.lab-curve-guides');
  let values = labCurveDefault();
  let movingPoint = null;
  let hoveredPoint = null;
  let selectedPoint = null;

  function showReadout() {
    const index = movingPoint ?? hoveredPoint ?? selectedPoint;
    readout.toggleAttribute('hidden', index == null);
    guides.toggleAttribute('hidden', index == null);
    points.forEach((point, i) => point.toggleAttribute('data-active', i === index));
    if (index == null) return;
    const point = points[index];
    const x = point.getAttribute('cx'), y = point.getAttribute('cy');
    guides.setAttribute('d', `M${x} 7V103M31 ${y}H255`);
    readout.textContent = point.getAttribute('aria-valuetext');
  }

  function update(index, value) {
    if (index != null) {
      values[index][1] = Math.min(200, Math.max(10, Math.round(value)));
    }
    const coordinates = values.map(([x, y]) => [31 + x / 1440 * 224, 103 - y / 200 * 96]);
    graph.querySelector('polyline').setAttribute('points', coordinates.map(point => point.join(',')).join(' '));
    points.forEach((point, i) => {
      point.setAttribute('cx', coordinates[i][0]);
      point.setAttribute('cy', coordinates[i][1]);
      point.setAttribute('aria-valuenow', values[i][1]);
      point.setAttribute('aria-valuetext', `${values[i][0]} px · ${values[i][1]}%`);
    });
    demo.querySelector('[data-extra-curve-value]').textContent = [2, 3, 5].map(i => `${values[i][0]} px ${values[i][1]}%`).join(' · ');
    showReadout();
  }
  graph.addEventListener('pointerover', event => {
    const point = event.target.closest('[data-extra-point]');
    hoveredPoint = point ? Number(point.dataset.extraPoint) : null;
    showReadout();
  });
  graph.addEventListener('pointerleave', () => { hoveredPoint = null; showReadout(); });
  graph.addEventListener('focusin', event => {
    if (!event.target.matches('circle[tabindex]')) return;
    selectedPoint = Number(event.target.dataset.extraPoint);
    hoveredPoint = null;
    showReadout();
  });
  graph.addEventListener('pointerdown', event => {
    const point = event.target.closest('circle[tabindex]');
    if (!point || !event.isPrimary || event.button !== 0) return;
    selectedPoint = movingPoint = Number(point.dataset.extraPoint);
    report('');
    showReadout();
    graph.setPointerCapture(event.pointerId);
  });
  graph.addEventListener('pointermove', event => {
    if (movingPoint == null || !graph.hasPointerCapture(event.pointerId)) return;
    const position = new DOMPoint(event.clientX, event.clientY).matrixTransform(graph.getScreenCTM().inverse());
    update(movingPoint, (103 - position.y) / 96 * 200);
  });
  graph.addEventListener('lostpointercapture', () => { movingPoint = null; hoveredPoint = null; showReadout(); });
  graph.addEventListener('keydown', event => {
    if (demo.closest('fieldset').disabled || !event.target.matches('circle[tabindex]') ||
        !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const index = Number(event.target.dataset.extraPoint);
    selectedPoint = index;
    hoveredPoint = null;
    report('');
    update(index, values[index][1] + (event.key === 'ArrowUp' ? 1 : -1));
  });
  demo.querySelector('[data-extra-curve-reset]').onclick = () => {
    values = labCurveDefault();
    selectedPoint = hoveredPoint = null;
    update();
    report('已重置曲线');
  };
  update();
}

function labBindAdditional(host, item, report) {
  const demo = host.querySelector('.lab-extended');
  if (item.id === 'danmaku-color') labBindColorDialog(demo, report);
  if (item.id === 'scale-curve') labBindCurve(demo, report);
  demo.addEventListener('input', event => {
    const field = event.target;
    if (field.matches('[data-extra-progress]')) {
      demo.querySelector('progress').value = field.value;
      demo.querySelector('output').textContent = field.value + '%';
    }
    if (field.matches('[data-extra-nav-search]')) {
      const query = field.value.trim();
      demo.querySelectorAll('[data-extra-choice]').forEach(button => {
        button.hidden = !button.textContent.trim().includes(query);
      });
    }
    if (field.matches('.lab-font-popup input[type=search]')) {
      const terms = field.value.toLowerCase().trim().split(/\s+/);
      const options = [...demo.querySelectorAll('[data-extra-font-choice]')];
      options.forEach(option => {
        const text = (option.textContent + ' ' + option.dataset.extraFontChoice).toLowerCase();
        option.hidden = !terms.every(term => text.includes(term));
      });
      demo.querySelector('.lab-extra-copy').hidden = options.some(option => !option.hidden);
    }
  });
  demo.addEventListener('keydown', event => {
    const target = event.target;
    if (target.matches('.lab-font-popup input[type=search]') && ['ArrowDown', 'Enter'].includes(event.key)) {
      const first = demo.querySelector('[data-extra-font-choice]:not([hidden])');
      if (first) {
        event.preventDefault();
        if (event.key === 'Enter') first.click();
        else first.focus();
      }
    }
    const group = target.closest('.lab-extra-choices');
    if (!group || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    const choices = [...group.querySelectorAll('button:not(:disabled,[hidden])')];
    if (!choices.length) return;
    event.preventDefault();
    const delta = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
    const next = choices[(choices.indexOf(target) + delta + choices.length) % choices.length];
    next.click();
    next.focus();
  });
  demo.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.matches('[data-extra-refresh]')) {
      const started = performance.now();
      const glyph = button.querySelector('.lab-glyph');
      const originalIcon = glyph.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.classList.add('lab-spinner');
      glyph.innerHTML = labIcon('qt-reconnect');
      report('正在统计图片缓存…');
      window.setTimeout(() => {
        const elapsed = ((performance.now() - started) / 1000).toFixed(1);
        if (!button.isConnected) return;
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.classList.remove('lab-spinner');
        glyph.innerHTML = originalIcon;
        report(`统计完成 · 24.8 MB · 耗时 ${elapsed} 秒`);
      }, 900);
    } else if (button.matches('[data-extra-disclosure]')) {
      const opened = button.getAttribute('aria-expanded') !== 'true';
      button.setAttribute('aria-expanded', opened);
      demo.querySelector('.lab-extra-copy').hidden = !opened;
    } else if (button.matches('[data-extra-font-choice]')) {
      demo.querySelectorAll('[data-extra-font-choice]').forEach(option => option.setAttribute('aria-pressed', option === button));
      const opener = demo.querySelector('[data-extra-font]');
      const name = button.getAttribute('aria-label');
      opener.querySelector('.lab-label').textContent = name;
      button.closest('[popover]').hidePopover();
      opener.focus();
      report('已选 ' + name);
    } else if (button.matches('[data-extra-choice]')) {
      demo.querySelectorAll('[data-extra-choice]').forEach(option => option.setAttribute('aria-pressed', option === button));
      const content = demo.querySelector('[data-extra-content]');
      if (content) content.textContent = button.dataset.extraChoice;
      const heading = demo.querySelector('[data-extra-heading]');
      if (heading) {
        heading.textContent = button.textContent.trim();
        demo.querySelector('[data-extra-description]').textContent = button.dataset.extraChoice === '主题'
          ? '设置主题、背景与界面分区样式' : '设置播放与声音';
      }
      if (!content) report('已选 ' + button.dataset.extraChoice);
    } else if (button.matches('[data-extra-switch]')) {
      const active = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', active);
      if (item.id === 'sidebar-toggle') button.querySelector('.lab-label').textContent = active ? '»' : '«';
      report(item.id === 'sidebar-toggle' ? (active ? '关注栏已收起' : '关注栏已展开')
        : (active ? '已进入多选管理' : '已退出多选管理'));
    } else if (button.matches('[data-extra-menu-item]')) {
      button.closest('[popover]').hidePopover();
      report('已选择 ' + button.textContent.trim());
    }
  });
}
