const icons = {
  settings: '<circle cx="12" cy="12" r="3"/><path d="M9 3h6l.8 3 2.7 1.5 3-.6 2 4-2.1 2.3-.4 3 1.7 2.3-3.5 3-2.8-1.1-2.7.6-1.7 2h-4l-1.4-2.4-2.7-1.4-2.8.5-2-3.9L4.8 14l.3-3-1.6-2.4L7 5.4l2 .6z" transform="translate(2 2) scale(.83)"/>',
  display: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  chat: '<path d="M20 15a2 2 0 0 1-2 2h-8l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2zM7 9h9m-9 4h6"/>',
  circle: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
  bell: '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zm5 3h4"/>',
  keyboard: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h1m3 0h1m3 0h1m3 0h1m-13 4h1m3 2h6m2-2h1"/>',
  folder: '<path d="M3 6h7l2 3h9v10H3z"/>',
  minimize: '<path d="M4 15h16M7 7h10"/>',
  box: '<path d="m3 7 9-4 9 4v10l-9 4-9-4zm0 0 9 5 9-5m-9 5v9"/>',
  update: '<path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  pause: '<path d="M9 5v14m6-14v14"/>',
  play: '<path d="m8 5 11 7-11 7z" fill="currentColor" stroke="none"/>',
  refresh: '<path d="M20 10a8 8 0 1 0-2 8m2-14v6h-6"/>',
  volume: '<path d="M3 9h4l5-4v14l-5-4H3zm12 0a4 4 0 0 1 0 6m2-9a8 8 0 0 1 0 12"/>',
  mute: '<path d="M3 9h4l5-4v14l-5-4H3zm12 0 6 6m0-6-6 6"/>',
  fullscreen: '<path d="M3 8V3h5m8 0h5v5m0 8v5h-5m-8 0H3v-5"/>',
  close: '<path d="m6 6 12 12m0-12L6 18"/>',
  pin: '<path d="m8 3 10 10-4 1-3 4-5-5 4-3zm0 12-5 6"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  more: '<path d="M5 12h.01m7 0h.01m7 0h.01" stroke-width="3"/>',
  alert: '<path d="m12 3 10 17H2zm0 6v4m0 4h.01"/>',
};

const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const iconButton = (name, label, attributes = '', size = '') => `<button type="button" class="control iconbtn ${size}" title="${label}" aria-label="${label}" ${attributes}>${icon(name)}</button>`;
const button = (label, type = '', attributes = '') => `<button type="button" class="btn ${type}" ${attributes}>${label}</button>`;
const toggle = (label, checked) => `<button class="toggle" type="button" role="switch" aria-label="${label}" aria-checked="${checked}"></button>`;
const select = (label, options) => `<select class="select" aria-label="${label}">${options.map(option => `<option>${option}</option>`).join('')}</select>`;
const segment = (label, values) => `<span class="segment" role="group" aria-label="${label}">${values.map((value, i) => `<button type="button" aria-pressed="${i === 0}">${value}</button>`).join('')}</span>`;
const stepper = (label, value, unit = '') => `<span class="stepper" data-min="1" data-max="30">${iconButton('minus', `减少${label}`, 'data-step="-1"', 'smaller')}<output data-value="${value}" data-unit="${unit}">${value}${unit}</output>${iconButton('plus', `增加${label}`, 'data-step="1"', 'smaller')}</span>`;
const range = (label, value) => `<span class="inline"><input class="range" aria-label="${label}" type="range" min="0" max="100" value="${value}"><output class="value">${value}</output></span>`;
const mark = '<span class="spinner" aria-hidden="true"></span>';
const progress = (value) => `<span class="bar" role="progressbar" aria-label="下载进度" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="100"><i style="width:${value}%"></i></span>`;
const mini = (title, hint = '') => `<div class="mini-card"><strong>${title}</strong>${hint ? `<p>${hint}</p>` : ''}</div>`;
const identity = '../../assets/logo.svg';
const media = '../assets/screenshots/overview1_Landscape_mode.png';
const themes = [['dark', '深色'], ['light', '浅色']];

const settingsNav = [
  ['settings', '常规'], ['display', '外观'], ['chat', '弹幕'], ['circle', '录制'],
  ['bell', '通知'], ['keyboard', '快捷键'], ['folder', '主播独立设置'],
  ['minimize', '托盘行为'], ['box', '插件'], ['update', '软件更新'], ['info', '诊断与反馈'],
];
const row = (label, control, hint = '', key = '') => `<div class="setting-row"><span class="setting-label">${label}${hint ? `<span class="setting-detail">${hint}</span>` : ''}</span><span class="inline" ${key ? `data-setting="${key}"` : ''}>${control}</span></div>`;
const section = (iconName, title, rows) => `<section class="setting-card"><h4>${icon(iconName)}${title}</h4>${rows.join('')}</section>`;
const themeCaption = (theme, label) => `<figcaption class="caption"><i class="${theme === 'light' ? 'light-dot' : ''}"></i>${label}</figcaption>`;

const settings = (theme, label) => `<figure>${themeCaption(theme, label)}<div class="app" data-theme="${theme}">
  <div class="win"><img src="${identity}" alt="">设置<small aria-hidden="true">— ×</small></div>
  <div class="settings-layout">
    <div class="rail" aria-label="设置分类">${settingsNav.map(([name, title], i) => `<span class="${i === 0 ? 'current' : ''}">${icon(name)}${title}</span>`).join('')}</div>
    <div class="settings-content">
      <h3>常规</h3><p>设置新建画面格和关注列表的默认行为。</p>
      ${section('volume', '播放与声音', [
        row('新建格子的初始音量', range('新建格子的初始音量', 68), '', 'volume'),
        row('新建格子初始静音', toggle('新建格子初始静音', false), '', 'initialMute'),
        row('全屏只播放该路声音', toggle('全屏只播放该路声音', true), '', 'solo'),
      ])}
      ${section('folder', '关注与预览', [
        row('关注列表刷新间隔', stepper('关注列表刷新间隔', 2, ' 分钟'), '', 'refresh'),
        row('关注栏直播预览', toggle('关注栏直播预览', true), '', 'preview'),
      ])}
      ${section('display', '编解码', [row('本机解码方式', select('本机解码方式', ['自动', '软件解码']), '', 'decoder')])}
      <div class="save" role="status">${icon('check')}设置已保存</div>
    </div>
  </div></div></figure>`;

const player = (theme, label) => `<figure>${themeCaption(theme, label)}<div class="player" data-theme="${theme}">
  <div class="tile-stage">
    <img class="frame" src="${media}" alt="取自项目截图的直播示例画面">
    <div class="tile-head"><div class="overlay-group room"><span class="pill" data-room-status>● 直播中</span><strong>直播间示例</strong></div>
    <div class="overlay-group">
      <select class="select" data-quality aria-label="切换画质"><option>原画</option><option>高清</option></select>
      ${iconButton('refresh', '重新连接', 'data-player-action="refresh"')}
    </div></div>
    <div class="tile-feedback" role="status" hidden></div>
    <div class="tile-foot"><div class="overlay-group">
      ${iconButton('pause', '暂停播放', 'data-player-action="pause" aria-pressed="false"')}
      ${iconButton('volume', '静音', 'data-player-action="mute" aria-pressed="false"')}
      ${iconButton('chat', '切换画面弹幕', 'data-player-action="chat" aria-pressed="true"')}
    </div></div>
  </div>
  <div class="tile-info"><span>哔哩哔哩 · 单路播放</span><span data-stream-info>1920×1080 · 60 fps</span></div>
</div></figure>`;

const sampleProgress = () => `<span class="inline">${progress(64)}<span class="value">64%</span></span>`;
const cardSearch = '<input type="search" class="short-input" aria-label="搜索关注" placeholder="搜索主播或分组">';
const previewAvatar = (label, extra = '') => `<span class="avatar ${extra}" title="${label}">${label}</span>`;
const menu = (title, options) => `<details class="mini-details"><summary>${title}</summary>${options.map(option => `<div class="mini-card">${option}</div>`).join('')}</details>`;
const curve = '<svg class="curve" viewBox="0 0 100 40" aria-label="缩放曲线示意" role="img"><path fill="none" stroke="currentColor" stroke-width="2" d="M6 32c20 0 20-21 44-21 21 0 20-5 44-5"/><circle r="2.5" cx="6" cy="32" fill="currentColor"/><circle r="2.5" cx="50" cy="11" fill="currentColor"/><circle r="2.5" cx="94" cy="6" fill="currentColor"/></svg>';
const dialogExample = (trigger, title, body, action) => `<span class="vertical-demo">
  ${button(trigger, '', 'data-open-dialog')}
  <dialog class="draft-dialog" aria-label="${title}"><h4>${title}</h4>${body}
    <form method="dialog" class="dialog-actions"><button class="btn" value="cancel">取消</button><button class="btn primary" value="apply">${action}</button></form>
  </dialog>
</span>`;
const colorExample = dialogExample('选择颜色', '主题强调色',
  '<p>查看选中色和对应的十六进制值。</p><label class="swatch-row"><input type="color" value="#739bfd" aria-label="选取颜色" data-color><output>#739BFD</output></label>', '应用颜色');
const segmentedExample = `<div class="segment-example">
  <div class="segment" role="group" aria-label="全部展开后的收起方式" data-example-segment>
    <span class="indicator" aria-hidden="true"></span>
    ${button('全部收起', '', 'data-segment-choice="all" aria-pressed="true"')}
    ${button('恢复原状', '', 'data-segment-choice="previous" aria-pressed="false"')}
  </div>
  <output class="segment-label" data-example-value aria-live="polite">当前选择：全部收起</output>
</div>`;

// Existing names are the public exports of ddm.ui. HTML samples use draft styling.
const components = [
  ['基础与承载', 'ActionButton', '操作按钮', '普通设置操作，可指定主次层级。', button('应用设置')],
  ['基础与承载', 'TitleLabel', '设置标题', '突出组标题，建立阅读顺序。', '<strong>播放与声音</strong>'],
  ['基础与承载', 'HintLabel', '说明文字', '较弱的视觉层级，长说明可换行。', '<span class="soft">重启后恢复上次布局。</span>'],
  ['基础与承载', 'page_header', '设置页头', '同处呈现页名和一句说明。', mini('常规', '管理播放默认值')],
  ['基础与承载', 'ElidedLabel', '可省略标签', '窄列单行省略，悬停可读全名。', '<span class="ellipsis" title="今天在海边散步并分享拍摄心得">今天在海边散步并分享拍摄心得</span>'],
  ['基础与承载', 'SettingsSurface', '设置卡片表面', '分组底板、边框和轻高光。', mini('关注与预览', '刷新间隔 · 直播预览')],
  ['基础与承载', 'continuous_path', '连续圆角', '供自绘控件复用的形状示例。', '<span class="mini-card" style="border-radius:15px;width:92px;text-align:center">圆角底板</span>'],
  ['基础与承载', 'Avatar', '头像', '栏目和关注条中的主体识别。', previewAvatar('遥')],
  ['基础与承载', 'RoomStrip', '关注头像条', '聚合多个直播间入口。', previewAvatar('遥') + previewAvatar('小') + previewAvatar('林')],
  ['基础与承载', 'PinnedArc', '置顶标识', '头像周围的置顶层提示。', previewAvatar('遥', 'pin')],
  ['基础与承载', 'circular_pixmap', '圆形图片裁切', '用共享裁切函数生成头像图。', `<span class="avatar"><img src="${identity}" alt="圆形裁切示例"></span>`],
  ['筛选与表单', 'ToggleSwitch', '开关', '即时切换二选一设置。', toggle('自动刷新', true)],
  ['筛选与表单', 'SegmentedControl', '分段选择', '设置 › 常规 › 关注与预览 › 全部展开后的收起方式。', segmentedExample],
  ['筛选与表单', 'SelectControl', '下拉选择', '收起后显示当前值，支持键盘选择。', select('解码方式', ['自动', '软件解码'])],
  ['筛选与表单', 'FontSelectControl', '字体下拉', '用下拉表面承载字体选项。', select('字体', ['系统字体', '思源黑体'])],
  ['筛选与表单', 'step_button', '加减图标按钮', '步进操作的单个点击入口。', iconButton('minus', '减少') + iconButton('plus', '增加')],
  ['筛选与表单', 'StepperControl', '步进器', '数值与加减控制组成一组。', stepper('刷新间隔', 2)],
  ['筛选与表单', 'SettingsSlider', '滑块', '连续调节，值同步更新。', range('音量', 68)],
  ['筛选与表单', 'SettingsValueLabel', '数值标签', '数值用等宽数字保持对齐。', '<span class="value">68%</span>'],
  ['筛选与表单', 'ColorDialog', '选色弹层', '选择颜色并查看十六进制值。', colorExample],
  ['筛选与表单', 'ScaleCurveControl', '缩放曲线', '曲线与控制点显示比例变化。', curve],
  ['导航与反馈', 'SettingsProgressBar', '进度条', '显示确定进度和当前百分比。', sampleProgress()],
  ['导航与反馈', 'DisclosureButton', '展开条', '切换附属内容展开与收起。', menu('编解码设置', ['硬件解码', '源格式'])],
  ['导航与反馈', 'AnimatedDialog', '对话框', '确认动作及其结果说明。', dialogExample('打开弹窗', '重启并应用', '<p>重启后，暂存的插件更新将生效。</p>', '重启并应用')],
  ['导航与反馈', 'AnimatedMenu', '弹出菜单', '聚合同一入口下的上下文动作。', menu('更多操作', ['打开详情', '复制链接'])],
  ['导航与反馈', 'SlidingTabs', '页签', '在同一区域切换内容。', segment('插件页签', ['已安装', '商店'])],
  ['导航与反馈', 'SettingsStack', '设置页面切换', '导航切换与当前页标题联动。', segment('设置页面示例', ['常规', '外观']) + '<span class="chip" data-stack-label>常规</span>'],
  ['导航与反馈', 'BarIconButton', '工具栏图标按钮', '紧凑图标和独立命中区域。', iconButton('more', '更多操作')],
  ['导航与反馈', 'NavigationButton', '功能栏按钮', '用于主界面的功能入口。', iconButton('bell', '打开通知', 'data-demo-press aria-pressed="false"')],
  ['播放控件', 'TileButton', '播放格按钮', '单路播放入口的统一尺寸。', button('原画 ' + icon('down'))],
  ['播放控件', 'VolumeButton', '音量按钮', '切换静音并提示当前状态。', iconButton('volume', '静音', 'data-demo-press="mute" aria-pressed="false"')],
  ['播放控件', 'RecordingButton', '录制按钮', '录制开始与停止切换。', iconButton('circle', '切换录制', 'data-demo-press aria-pressed="false"')],
  ['播放控件', 'SidebarToggleButton', '侧栏开关', '切换侧栏的可见状态。', iconButton('panel', '切换侧栏', 'data-demo-press aria-pressed="true"')],
  ['播放控件', 'PauseButton', '暂停按钮', '显示下一步是暂停还是播放。', iconButton('pause', '暂停播放', 'data-demo-press="pause" aria-pressed="false"')],
  ['播放控件', 'RefreshButton', '重连按钮', '展示重连开始时的等待反馈。', iconButton('refresh', '重新连接', 'data-demo-refresh')],
  ['播放控件', 'DanmakuToggleButton', '弹幕开关', '明确区分弹幕启用与关闭。', iconButton('chat', '切换画面弹幕', 'data-demo-press aria-pressed="true"')],
  ['设计候选', 'SearchField', '搜索框外观', '现有搜索行为沿用；候选为统一视觉、焦点与清空入口。', cardSearch, true],
  ['设计候选', 'StatusBadge', '状态徽标', '用文字和图形表达开播或错误。', '<span class="pill">● 直播中</span><span class="chip error">播放失败</span>', true],
  ['设计候选', 'AsyncActionFeedback', '异步操作结果', '在动作附近显示正在进行、成功或可重试。', button('检查更新', 'primary', 'data-demo-async') + '<span class="soft" role="status">待检查</span>', true],
  ['设计候选', 'EmptyState', '空状态', '说明当前为何为空，并给出一个可用入口。', `<div class="mini-empty">${icon('box')}<strong>没有已安装的插件</strong>${button('浏览插件商店', 'primary')}</div>`, true],
  ['设计候选', 'PlaybackStatusOverlay', '播放状态叠层', '统一区分连接中和播放失败，保留重试入口。', `<div class="vertical-demo"><span class="chip error">${icon('alert')}播放失败</span>${button('重新连接', '', 'data-demo-retry')}</div>`, true],
  ['设计候选', 'SettingRow', '设置行组合', '标签、补充说明和控件有固定对齐关系。', '<span class="soft">关注栏预览</span>' + toggle('关注栏预览', true), true],
  ['设计候选', 'MediaControlSurface', '媒体控制栏表面', '视频上的局部底板及表现层遮罩。', `<span class="overlay-group">${iconButton('pause', '暂停', 'data-demo-press="pause" aria-pressed="false"', 'smaller')}${iconButton('chat', '弹幕', 'data-demo-press aria-pressed="true"', 'smaller')}</span>`, true],
];

const buttonStates = ['默认', '悬停', '按下', '键盘焦点', '选中', '禁用', '加载'];
const buttonFamilies = [
  ['主操作', '应用', 'primary'],
  ['次操作', '详情', ''],
  ['危险操作', '移除', 'danger'],
  ['图标按钮', '刷新', 'iconbtn'],
];

function renderMatrices() {
  document.getElementById('matrices').innerHTML = themes.map(([theme, title]) => `<div data-theme="${theme}" class="matrix-panel"><table>
    <caption>${title}</caption><thead><tr><th scope="col">按钮类型</th>${buttonStates.map(name => `<th scope="col">${name}</th>`).join('')}</tr></thead>
    <tbody>${buttonFamilies.map(([family, label, style]) => `<tr><th scope="row">${family}</th>${buttonStates.map((state, i) => {
      const iconOnly = style === 'iconbtn';
      const extraClass = ['', 'is-hover', 'is-down', 'is-focus'][i] || '';
      const attributes = i === 4 ? 'aria-pressed="true"' : i === 5 ? 'disabled' : i === 6 ? 'disabled aria-busy="true"' : '';
      const sample = i === 6 ? mark + (iconOnly ? '' : '处理中') : iconOnly ? icon('refresh') : label;
      return `<td>${button(sample, `${style} ${extraClass}`, `aria-label="${family} · ${state}" ${attributes}`)}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div>`).join('');
}

let selectedComponent = 'SegmentedControl';
let slidePreview = true;

function renderShowcase(component) {
  const showcase = document.getElementById('showcase');
  if (!component) {
    showcase.innerHTML = '<p class="desc">没有匹配的控件。</p>';
    delete showcase.dataset.activeComponent;
    return;
  }
  const [, name, label, description, preview, proposed] = component;
  showcase.dataset.activeComponent = name;
  const notes = name === 'SegmentedControl' ? `<dl class="example-notes">
    <div><dt>共同底板</dt><dd>两个选项设置同一个行为，只选其一。</dd></div>
    <div><dt>选中块</dt><dd>独立的亮块和较重的文字表示当前选择。</dd></div>
    <div><dt>实装对照</dt><dd>在<a href="#control-collapse">该设置的详情</a>查看当前 Qt 外观。</dd></div>
  </dl>` : '';
  const specimens = `<div class="specimens">${themes.map(([theme, title]) =>
    `<figure class="specimen" data-theme="${theme}"><figcaption>${title}</figcaption><div class="demo">${preview}</div></figure>`).join('')}</div>`;
  const body = name === 'SegmentedControl' ? `<div class="example-tools">
    <div class="filters" role="group" aria-label="分段选择示例内容">
      <button type="button" aria-controls="segment-preview" aria-pressed="true" data-segment-view="segment-preview">实时演示</button>
      <button type="button" aria-controls="segment-usage" aria-pressed="false" data-segment-view="segment-usage">使用说明</button>
    </div>
    <button type="button" class="example-toggle" data-slide-preview aria-pressed="${slidePreview}">滑动动效${slidePreview ? '已开启' : '已关闭'}</button>
    </div>
    <div id="segment-preview">${specimens}${notes}</div>
    <div id="segment-usage" class="example-usage" hidden>
      <p><strong>全部收起</strong>　收起所有关注文件夹。</p>
      <p><strong>恢复原状</strong>　只收起本次全部展开前已收起的文件夹。无记录时全部收起。</p>
      <p><strong>键盘操作</strong>　Tab 移到可用选项，Enter 或 Space 立即选择。开启系统减少动态效果时选中块也立即更新。</p>
    </div>` : specimens;
  showcase.innerHTML = `<header><div class="showcase-title"><h2>${label}</h2><span class="kind ${proposed ? 'proposed' : ''}">${proposed ? '新增候选' : '候选样式'}</span></div>
    <div class="code">${name}</div><p class="component-description">${description}</p></header>${body}`;
}

function showComponent(name) {
  const component = components.find(([, id]) => id === name);
  if (!component) return;
  selectedComponent = name;
  document.querySelectorAll('[data-component]').forEach(button => {
    if (button.dataset.component === name) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  });
  renderShowcase(component);
}

function renderCatalog() {
  const search = document.getElementById('search').value.trim().toLowerCase();
  const filter = document.querySelector('[data-filter][aria-pressed=true]').dataset.filter;
  const results = components.filter(([group, name, label, description, , proposed]) =>
    (filter === 'all' || Boolean(proposed) === (filter === 'proposed')) &&
    `${group} ${name} ${label} ${description}`.toLowerCase().includes(search));
  const groups = new Map([['筛选与表单', []]]);
  for (const component of results) {
    const category = component[0];
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(component);
  }
  document.getElementById('count').textContent = `显示 ${results.length} / ${components.length} 项`;
  document.getElementById('components').innerHTML = [...groups].filter(([, items]) => items.length).map(([group, items]) =>
    `<section class="catalog-group"><h3>${group}</h3>${items.map(([, name, label]) =>
      `<button type="button" data-component="${name}">${label}</button>`).join('')}</section>`).join('');
  const current = results.find(([, name]) => name === selectedComponent) ?? results[0];
  if (current) showComponent(current[1]);
  else renderShowcase();
}

const playerState = {muted: false, paused: false, chat: true};
let reconnectTimer;
function showScenario(scenario) {
  clearTimeout(reconnectTimer);
  document.querySelectorAll('[data-scenario]').forEach(button => button.setAttribute('aria-pressed', button.dataset.scenario === scenario));
  document.querySelectorAll('.tile-feedback').forEach(item => {
    item.hidden = scenario === 'playing';
    item.innerHTML = scenario === 'loading' ? `<strong>${mark} 正在连接</strong><p>正在恢复这一路画面。</p>` :
      scenario === 'error' ? `<strong class="err">${icon('alert')} 播放失败</strong><p>直播线路中断，可尝试重新连接。</p>${button('重新连接', 'primary', 'data-player-action="refresh"')}` : '';
    item.querySelector('.spinner')?.classList.add('animate-spin');
  });
  document.querySelectorAll('[data-room-status]').forEach(item => {
    item.textContent = scenario === 'playing' ? '● 直播中' : scenario === 'error' ? '! 异常' : '◌ 连接中';
    item.className = scenario === 'playing' ? 'pill' : `chip ${scenario === 'error' ? 'error' : ''}`;
  });
  document.querySelectorAll('[data-stream-info]').forEach(item => {
    item.textContent = scenario === 'playing' ? '1920×1080 · 60 fps' : scenario === 'loading' ? '等待视频信号' : '线路中断';
  });
}

function togglePressed(control, pressed, kind) {
  control.setAttribute('aria-pressed', pressed);
  if (kind === 'mute' || kind === 'pause') {
    const state = kind === 'mute' ? (pressed ? ['mute', '取消静音'] : ['volume', '静音']) :
      (pressed ? ['play', '继续播放'] : ['pause', '暂停播放']);
    control.innerHTML = icon(state[0]);
    control.title = state[1];
    control.setAttribute('aria-label', state[1]);
  }
}

function siblings(control, selector) {
  const key = control.closest('[data-setting]')?.dataset.setting;
  return key ? document.querySelectorAll(`[data-setting="${key}"] ${selector}`) : [control];
}

function setTab(tab, focus = false) {
  document.querySelectorAll('[role=tab]').forEach(item => {
    const selected = item === tab;
    item.setAttribute('aria-selected', selected);
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
  });
  if (focus) tab.focus();
}

document.getElementById('settings-pair').innerHTML = themes.map(([theme, label]) => settings(theme, label)).join('');
document.getElementById('player-pair').innerHTML = themes.map(([theme, label]) => player(theme, label)).join('');
renderMatrices();
renderCatalog();
document.getElementById('search').addEventListener('input', renderCatalog);

document.querySelector('.top-nav').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const tabs = [...document.querySelectorAll('[role=tab]')];
  const i = tabs.indexOf(event.target);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
    (i + tabs.length + (event.key === 'ArrowLeft' ? -1 : 1)) % tabs.length;
  event.preventDefault();
  setTab(tabs[next], true);
});

document.addEventListener('input', event => {
  const input = event.target;
  if (input.matches('.range')) {
    siblings(input, '.range').forEach(range => {
      range.value = input.value;
      range.nextElementSibling.textContent = input.value;
    });
  } else if (input.matches('.select')) {
    const targets = input.matches('[data-quality]') ? document.querySelectorAll('[data-quality]') : siblings(input, '.select');
    targets.forEach(select => { select.value = input.value; });
  } else if (input.matches('[data-color]')) {
    input.nextElementSibling.textContent = input.value.toUpperCase();
  }
});

document.addEventListener('click', event => {
  const clicked = event.target.closest('button');
  if (!clicked) return;
  if (clicked.matches('[role=tab]')) setTab(clicked);
  if (clicked.matches('[data-component]')) showComponent(clicked.dataset.component);
  if (clicked.matches('[data-filter]')) {
    document.querySelectorAll('[data-filter]').forEach(button => button.setAttribute('aria-pressed', button === clicked));
    renderCatalog();
  }
  if (clicked.matches('[data-scenario]')) showScenario(clicked.dataset.scenario);
  if (clicked.matches('[data-segment-view]')) {
    document.querySelectorAll('[data-segment-view]').forEach(button => {
      const shown = button === clicked;
      button.setAttribute('aria-pressed', shown);
      document.getElementById(button.dataset.segmentView).hidden = !shown;
    });
    document.querySelector('[data-slide-preview]').hidden = clicked.dataset.segmentView !== 'segment-preview';
  }
  if (clicked.matches('[data-slide-preview]')) {
    slidePreview = !slidePreview;
    clicked.setAttribute('aria-pressed', slidePreview);
    clicked.textContent = '滑动动效' + (slidePreview ? '已开启' : '已关闭');
    if (!slidePreview) document.querySelectorAll('[data-example-segment] .indicator').forEach(indicator => indicator.classList.remove('is-sliding'));
  }
  if (clicked.matches('[data-open-dialog]')) clicked.nextElementSibling.showModal();
  if (clicked.matches('[data-demo-retry]')) {
    const status = clicked.previousElementSibling;
    clicked.disabled = true;
    status.className = 'chip';
    status.textContent = '正在连接';
    setTimeout(() => {
      clicked.disabled = false;
      status.textContent = '已恢复播放';
    }, 650);
  }
  if (clicked.matches('[role=switch]')) {
    const checked = clicked.getAttribute('aria-checked') !== 'true';
    siblings(clicked, '[role=switch]').forEach(button => button.setAttribute('aria-checked', checked));
  }
  if (clicked.matches('[data-step]')) {
    const stepper = clicked.closest('.stepper');
    const value = Number(stepper.querySelector('output').dataset.value) + Number(clicked.dataset.step);
    const bounded = Math.max(Number(stepper.dataset.min), Math.min(Number(stepper.dataset.max), value));
    siblings(clicked, '.stepper button').forEach(button => {
      const output = button.closest('.stepper').querySelector('output');
      output.dataset.value = bounded;
      output.textContent = bounded + output.dataset.unit;
    });
  }
  if (clicked.matches('[data-segment-choice]')) {
    const choice = clicked.dataset.segmentChoice;
    document.querySelectorAll('[data-example-segment] .indicator').forEach(indicator => {
      indicator.classList.toggle('is-sliding', slidePreview && event.detail > 0);
    });
    document.querySelectorAll('[data-segment-choice]').forEach(option =>
      option.setAttribute('aria-pressed', option.dataset.segmentChoice === choice));
    document.querySelectorAll('[data-example-value]').forEach(output => {
      output.textContent = '当前选择：' + clicked.textContent;
    });
  } else if (clicked.parentElement.matches('.segment')) {
    [...clicked.parentElement.children].forEach(button => button.setAttribute('aria-pressed', button === clicked));
    const label = clicked.closest('.demo').querySelector('[data-stack-label]');
    if (label) label.textContent = clicked.textContent;
  }
  const action = clicked.dataset.playerAction;
  if (action === 'refresh') {
    const retry = clicked.closest('.tile-feedback');
    if (retry) retry.closest('.player').querySelector('.tile-head [data-player-action=refresh]').focus();
    showScenario('loading');
    reconnectTimer = setTimeout(() => showScenario('playing'), 1200);
  } else if (['pause', 'mute', 'chat'].includes(action)) {
    const key = {pause: 'paused', mute: 'muted', chat: 'chat'}[action];
    playerState[key] = !playerState[key];
    document.querySelectorAll(`[data-player-action="${action}"]`).forEach(button => togglePressed(button, playerState[key], action));
  }
  if (clicked.matches('[data-demo-press]')) togglePressed(clicked, clicked.getAttribute('aria-pressed') !== 'true', clicked.dataset.demoPress);
  if (clicked.matches('[data-demo-async],[data-demo-refresh]')) {
    const isAsync = clicked.matches('[data-demo-async]');
    const label = clicked.nextElementSibling;
    clicked.disabled = true;
    clicked.innerHTML = (isAsync ? '检查中 ' : '') + mark.replace('spinner', 'spinner animate-spin');
    if (isAsync) label.textContent = '正在查询';
    setTimeout(() => {
      clicked.disabled = false;
      clicked.innerHTML = isAsync ? '再次检查' : icon('refresh');
      if (isAsync) label.textContent = '检查完成';
    }, 700);
  }
});
