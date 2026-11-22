const labMatchRevision = '73bb82649698dfe55a7f8e92d159e85591ddae09';
const labMatchSource = file => `plugins/match_sync/${file}`;
const labIconCatalog = [
  ...labSourceGlyphs.map(([group, id, label, source, svg]) => ({group, id, label, source, svg})),
  ...[
    ['playback_controls.py', [
      ['qt-pause', '暂停'], ['play', '继续播放'], ['qt-volume', '双声道'], ['qt-mute', '静音'],
      ['L', '左声道'], ['R', '右声道'], ['qt-reconnect', '刷新／重连'], ['弹', '画面弹幕'],
      ['settings', '弹幕观看设置'], ['●', '录制状态'], ['«', '横屏收起侧栏'], ['»', '横屏展开侧栏'],
      ['⌃', '竖屏收起侧栏'], ['⌄', '竖屏展开侧栏'],
    ]],
    ['tile_widgets.py', [['⛶', '全屏'], ['×', '关闭一路']]],
    ['pip_window.py', [['qt-grid', '画中画组合'], ['qt-swap', '调整画中画位置'], ['pin', '置顶画中画'],
      ['qt-return', '返回监控室'], ['close', '关闭画中画'], ['volume', '画中画音量']]],
    ['caption_toolbar.py', [['qt-caption', '字幕内容'], ['A+', '加大字幕'], ['A−', '减小字幕'],
      ['refresh', '重置字幕位置'], ['qt-lock', '锁定字幕']]],
    ['notification_center.py', [['bell', '通知铃铛'], ['×', '关闭通知']]],
    ['update_notice.py', [['×', '关闭更新提示']]],
    ['follow_import_ui.py', [['…', '更多登录平台']]],
    ['settings_window.py', [['close', '关闭设置窗口']]],
    ['ui/toolbar.py', [['qt-check-stack', '多选管理'], ['↑↓', '关注排序']]],
    ['ui/stepper.py', [['plus', '增加数值'], ['minus', '减少数值']]],
    ['ui/select.py', [['down', '下拉选择']]],
    ['ui/disclosure.py', [['›', '展开详情']]],
    ['settings_streamer_profiles.py', [['›', '展开主播设置']]],
    ['settings_streamer_undo.py', [['⌃', '收起撤回提示'], ['⌄', '展开撤回提示']]],
    ['room_choice.py', [['check', '选中直播间']]],
    ['sidebar_widgets.py', [['◐', '切换深浅主题']]],
    ['folder_icons.py', [['folder', '系统文件夹'], ['qt-return', '系统智能文件夹']]],
    ['skin_gallery.py', [['qt-image', '添加背景'], ['qt-image-off', '默认背景']]],
    ['video_danmaku_settings.py', [['■', '弹幕颜色色样']]],
    ['danmaku_widgets.py', [['down', '回到底部']]],
    ['super_chat_widgets.py', [['×', '关闭醒目留言']]],
    ['video_super_chat.py', [['×', '关闭画面醒目留言']]],
    ['playback_badges.py', [['●', '连接状态']]],
    ['layout_picker.py', [['qt-grid', '布局缩略图']]],
    ['room_presets_ui.py', [['qt-grid', '直播间组合缩略图']]],
    ['pip_arrangements.py', [['qt-grid', '画中画布局缩略图']]],
    ['tray_preview.py', [['panel', '托盘布局示意']]],
    ['update_progress_ui.py', [['qt-reconnect', '更新等待指示']]],
  ].flatMap(([file, items]) => items.map(([glyph, label], i) => ({
    group: '自绘与字形', id: `paint-${file.split('/').pop().slice(0, -3)}-${i}`, label, source: `ddm/${file}`, glyph,
  }))),
  ...[
    ['应用窗口与托盘', 'assets/favicon.ico'], ['应用标识', 'assets/logo.svg'], ['应用标识 PNG', 'assets/logo.png'],
    ['哔哩哔哩', 'assets/platforms/bilibili.ico'], ['虎牙', 'assets/platforms/huya.png'],
    ['斗鱼', 'assets/platforms/douyu.ico'], ['抖音', 'assets/platforms/douyin.ico'],
    ['YouTube', 'assets/platforms/youtube.ico'], ['Twitch', 'assets/platforms/twitch.ico'],
    ['CHZZK', 'assets/platforms/chzzk.ico'], ['未知平台', 'assets/platforms/generic.svg'],
    ['Qt 下拉箭头', 'ddm/assets/arrow_down.png'], ['Qt 加载素材', 'ddm/assets/loading.gif'],
  ].map(([label, asset], i) => ({group: '应用与平台素材', id: `asset-${i}`, label, source: asset, asset})),
  ...[
    ['floating', '裁取悬浮画面', '<rect x="4" y="6" width="16" height="12" rx="2"/><rect x="13" y="12" width="5" height="4"/>'],
    ['region', '选择对照区域', '<path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5"/><rect x="9" y="9" width="6" height="6"/>'],
    ['assist', '辅助自动对齐', '<path d="M8 18V6m-3 3 3-3 3 3m5-3v12m-3-3 3 3 3-3"/>'],
    ['clock', '计时器对齐', '<circle cx="12" cy="13" r="7"/><path d="M12 6V3M9 3h6m-3 6v4l3 2"/>'],
    ['independent', '独立播放', '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="m10 8 6 4-6 4Z"/>'],
    ['resync', '重新匹配', icons.refresh],
    ['minimize', '收起对照／控制台', '<path d="M6 15h12"/>'],
    ['emote', '表情', '<circle cx="12" cy="12" r="7"/><path d="M9.5 10h.01m5 0h.01M9 13a3 3 0 0 0 6 0"/>'],
    ['gift', '礼物', '<rect x="6" y="11" width="12" height="8" rx="1"/><path d="M5 8h14v3H5zM12 8v11"/><ellipse cx="9.5" cy="6" rx="2.5" ry="2"/><ellipse cx="14.5" cy="6" rx="2.5" ry="2"/>'],
    ['save', '暂存弹幕', '<path d="M7 5h10v14l-5-4-5 4Z"/>'],
    ['live', '返回直播', '<path d="M5 12h11m-4-4 4 4-4 4m7-10v12"/>'],
    ['main', '主画面', '<rect x="4" y="4" width="16" height="12" rx="1"/><path d="M12 16v4m-4 0h8"/>'],
    ['chat-connected', '弹幕连接状态', '<path d="M5 5h14v10h-6l-5 4v-4H5Z"/><path d="M8 10h8"/>'],
    ['entry', '比赛二路入口', '<rect x="3" y="4" width="10" height="16" rx="2"/><rect x="16" y="8" width="5" height="12" rx="1"/>', 'plugin.py'],
  ].map(([id, label, svg, source = 'panels.py']) => ({group: '比赛二路插件', id: `match-${id}`, label, source, plugin: true, svg})),
];

const labIconsById = new Map(labIconCatalog.map(item => [item.id, item]));
const labIconGroups = [...new Set(labIconCatalog.map(item => item.group))];
const labIconSource = item => `../../${item.source}`;

function labInventoryGlyph(item) {
  if (item.asset) return `<img src="../../${item.asset}" alt="">`;
  if (item.svg) return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${item.svg}</svg>`;
  if (['L', 'R'].includes(item.glyph)) return labIcon('qt-volume').replace('>LR</text>', `>${item.glyph}</text>`);
  return item.glyph in icons || item.glyph in labQtGlyphs || item.glyph in labTileGlyphs
    ? labIcon(item.glyph) : `<span aria-hidden="true">${item.glyph}</span>`;
}

function labInventoryButton(item, attrs, label = item.label) {
  return `<button type="button" class="lab-control lab-inventory-button" ${attrs}
    title="${label}" aria-label="${label}">${labInventoryGlyph(item)}</button>`;
}

function labIconSpecimen() {
  const initial = labIconCatalog[0];
  const options = labIconGroups.map(group => `<optgroup label="${group}">${labIconCatalog.filter(item => item.group === group)
    .map(item => `<option value="${item.id}">${item.label}</option>`).join('')}</optgroup>`).join('');
  return `<div class="lab-extension lab-icon-specimen"><div class="lab-icon-toolbar">
      ${labInventoryButton(initial, 'data-icon-button data-primary')}
      <select class="lab-control" data-icon-picker aria-label="选择图标">${options}</select>
    </div>
    <a class="lab-link" data-icon-source href="${labIconSource(initial)}">${initial.label}的源码</a></div>`;
}

function labIconIndex() {
  return `<section class="lab-panel lab-icon-library"><h3>图标目录</h3><div class="lab-demo lab-icon-index">
    ${labIconGroups.map(group => `<section><h4>${group}</h4><div class="lab-icon-grid">
    ${labIconCatalog.filter(item => item.group === group).map(item => `<button class="lab-control" type="button"
      data-icon-pick="${item.id}">${labInventoryGlyph(item)}<span>${item.label}</span></button>`).join('')}
    </div></section>`).join('')}</div></section>`;
}

function labBindIconSpecimen(host, report) {
  const picker = host.querySelector('[data-icon-picker]');
  const button = host.querySelector('[data-icon-button]');
  const source = host.querySelector('[data-icon-source]');
  const index = host.closest('#playground-detail')?.querySelector('.lab-icon-index');
  const syncIndex = id => index?.querySelectorAll('[data-icon-pick]').forEach(option =>
    option.setAttribute('aria-pressed', option.dataset.iconPick === id));
  function select(id) {
    const item = labIconsById.get(id);
    picker.value = id;
    button.innerHTML = labInventoryGlyph(item);
    button.title = item.label;
    button.setAttribute('aria-label', item.label);
    if (item.plugin) {
      source.removeAttribute('href');
      source.title = labMatchRevision;
      source.textContent = `${labMatchRevision.slice(0, 7)} · ${labMatchSource(item.source)}`;
    } else {
      source.href = labIconSource(item);
      source.removeAttribute('title');
      source.textContent = `${item.label}的源码`;
    }
    syncIndex(id);
    report(`已选 ${item.label}`);
  }
  picker.addEventListener('change', () => select(picker.value));
  if (index) {
    syncIndex(picker.value);
    index.onclick = event => {
      const option = event.target.closest('[data-icon-pick]');
      if (option && !picker.matches(':disabled')) select(option.dataset.iconPick);
    };
  }
  button.addEventListener('click', () => report(`已触发 ${button.title}`));
}
