// Matches the Windows Qt capture rows in ui-control-library-qt-application.png.
const labApplicationControls = [
  ['room-search', '关注搜索框', '关注栏 › 搜索主播／房间号', 217, 'room_add_followed.py', '输入中文、拼音或房间号，查看结果与空态。'],
  ['room-add', '批量添加直播间', '关注栏 › 添加与导入', 280, 'room_add_panel.py', '每行一个房间号或直播间链接。选择文件夹后试用数量与错误反馈。'],
  ['room-picker', '关注直播间选择器', '添加直播间 › 从关注列表选择', 280, 'room_add_followed.py', '搜索关注项、筛选直播中并选择一项。'],
  ['follow-import', '导入关注列表', '添加与导入 › 导入关注', 232, 'follow_import_ui.py', '核对复选、已关注禁用和导入数量。'],
  ['follow-card', '关注卡片多选', '关注列表 › 多选管理', 212, 'sidebar_item.py', '选择卡片，查看主播标题和开播状态。'],
  ['folder-head', '关注文件夹标题', '关注列表 › 文件夹', 204, 'sidebar_folders.py', '展开或收起文件夹，也可进入行内重命名。'],
  ['folder-edit', '文件夹名称与图标', '关注列表 › 新建／编辑文件夹', 244, 'folder_icons.py', '填写名称、选择颜色，确认后立即显示。'],
  ['function-hub', '功能中心', '侧栏 › 功能中心', 233, 'workspace_controls.py', '搜索功能、切换固定状态，或打开插件管理入口。'],
  ['account-menu', '账号行与账号菜单', '关注栏底部 › 账号', 245, 'account_widgets.py', '打开账号操作菜单。示例使用虚构账号。'],
  ['layout-picker', '画面墙布局预设', '画面墙 › 布局预设', 238, 'layout_picker.py', '选择布局卡片，比较格子排列和选中态。'],
  ['room-preset', '保存直播间组合', '布局预设 › 我的组合', 232, 'room_presets_ui.py', '输入组合名并试用保存、取消及反馈。'],
  ['wall-remove', '移除画面选择', '画面墙 › 清空画面墙', 243, 'wall_removal.py', '选择未开播或全部直播，移除后可撤回。'],
  ['wall-quick', '画面墙全局设置', '画面墙 › 全局设置', 232, 'wall_quick_settings.py', '调整全局音量、画质、画面弹幕和弹幕浮窗。'],
  ['pip-composer', '画中画组合预览', '画中画 › 选择画面组合', 224, 'pip_preview.py', '调整示例组合列数，并选择主画面。'],
  ['pip-tools', '画中画工具栏', '画中画 › 悬停工具栏', 174, 'pip_window.py', '检查组合、调整位置、置顶、返回和关闭的反馈。'],
  ['pip-audio', '画中画单路音量', '画中画 › 多路音量', 203, 'picture_in_picture_audio.py', '查看主播名，切换静音并调整音量。'],
  ['volume-popup', '窄格音量浮层', '播放格 › 窄幅底栏', 104, 'playback_controls.py', '悬停或点击扬声器，试用竖向滑块。'],
  ['stream-state', '连接与播放状态', '播放格 › 画面叠层', 224, 'playback_badges.py', '切换连接、缓冲、播放与暂停，查看状态提示。'],
  ['stream-info', '直播流信息', '播放格 › 右键菜单', 163, 'stream_info.py', '打开弹窗，选择或复制示例编解码信息。'],
  ['caption-tools', '字幕浮动工具栏', '播放格 › 字幕位置工具', 214, 'caption_toolbar.py', '切换字幕内容、增减字号、复位和锁定。'],
  ['danmaku-panel', '弹幕格消息与工具', '画面墙 › 弹幕格', 225, 'danmaku_widgets.py', '切换跟随、返回底部、调字号和输入示例。'],
  ['super-chat', '醒目留言卡片', '弹幕格 › 醒目留言', 209, 'super_chat_widgets.py', '展开或收起内容，关闭后可恢复示例。'],
  ['shortcut-edit', '快捷键录入', '设置 › 快捷键', 231, 'settings_shortcuts.py', '聚焦录入框，按组合键，再试禁用与恢复默认。'],
  ['settings-caption', '设置窗口标题栏', '设置 › 窗口顶部', 196, 'settings_window.py', '核对标题与关闭按钮，点击可恢复示例。'],
  ['close-choice', '关窗去向选择', '主窗口 › 关闭', 156, 'system_tray.py', '选择隐藏到托盘或退出，并试用记住选择。'],
  ['cache-pie', '缓存分类环图', '数据与存储 › 图片缓存', 226, 'cache_settings.py', '点击分类环图或复选框，再试模拟清理。'],
  ['skin-library', '本地背景图库', '外观 › 背景素材', 231, 'skin_gallery.py', '选中默认背景或导入本地预览。图片只用于当前网页。'],
  ['blocked-users', '屏蔽用户列表', '弹幕 › 屏蔽用户', 228, 'settings_danmaku_blocking.py', '添加数字 UID，选择一项再移除。'],
  ['audio-response', '音量均衡响应图', '常规 › 音量均衡', 232, 'audio_normalization_ui.py', '修改响应参数，观察示例曲线。'],
  ['menu-order', '右键菜单顺序', '常规 › 播放格菜单', 225, 'tile_menu.py', '拖动条目或用按钮调整顺序，切换是否显示。'],
  ['notices', '通知中心与未读', '侧栏 › 通知', 149, 'notification_center.py', '打开通知、标记已读或清空示例记录。'],
  ['update-notice', '版本更新提示', '画面墙 › 更新提醒', 237, 'update_notice.py', '试用查看更新、关闭和恢复提醒。'],
  ['tray-layout', '托盘布局示意', '托盘菜单 › 布局预览', 176, 'tray_preview.py', '点击布局示意查看恢复窗口的反馈。'],
  ['record-path', '录制保存目录', '设置 › 录制', 236, 'settings_recording.py', '编辑路径，或用浏览入口切换示例目录。'],
  ['diagnostic-form', '诊断图片与导出', '设置 › 诊断与反馈', 238, 'settings_diagnostics.py', '添加或移除示例附件，试用导出反馈。'],
  ['plugin-remove', '删除插件确认', '设置 › 已安装插件', 147, 'settings_plugins.py', '检查确认与取消的焦点、颜色和反馈。'],
  ['smart-folder', '智能分组规则', '关注管理 › 新建智能文件夹', 240, 'sidebar_folders.py', '组合来源文件夹、开播状态与平台条件。'],
  ['account-platform', '登录平台选择', '关注栏 › 登录', 220, 'account_dialog.py', '切换平台按钮，查看所选平台。'],
  ['danmaku-source', '弹幕来源选择', '弹幕格 › 关联画面', 220, 'pane_source_picker.py', '展开头像列表，切换关联的画面。'],
  ['comment-actions', '单条弹幕工具条', '弹幕消息 › 右键', 240, 'danmaku_actions.py', '打开复制、复读和屏蔽动作。'],
  ['danmaku-float', '弹幕浮窗与收回', '弹幕格 › 浮动窗口', 224, 'danmaku_float_window.py', '切换浮窗并用占位按钮收回弹幕。'],
  ['caption-placement', '字幕位置与大小', '字幕工具 › 宿主位置预览', 230, 'caption_preview.py', '拖动字幕或用方向键移动，试用大小调节与复位。'],
  ['theme-editor', '主题自定义值', '外观 › 主题', 240, 'settings_theme_editor.py', '填写颜色值，切换字体并调整界面字号。'],
  ['skin-parts', '界面分区预览', '外观 › 界面美化', 230, 'skin_preview.py', '切换场景，点击分区后试换底色。'],
  ['notice-blur', '开播通知模糊预览', '通知 › 开播提醒', 234, 'settings_notifications.py', '开关直播封面，并调整背景模糊程度。'],
  ['streamer-profile', '主播独立设置卡', '主播设置 › 主播卡片', 288, 'settings_streamer_profiles.py', '在整组和单个主播间切换，修改画质和音量。'],
  ['startup-notice', '首次启动须知', '首次启动 › 用户须知', 200, 'user_notice.py', '滚动阅读试样，确认后查看反馈。'],
  ['settings-material', '视觉效果与设置布局', '外观 › 视觉效果', 248, 'settings_material_editor.py', '切换毛玻璃、阴影、分段指示器和设置卡片布局，试调底色不透明度。'],
].map(([id, title, location, width, file, usage], row) => ({
  id, title, location, width, usage, height: id === 'pip-tools' ? 24 : id === 'account-menu' ? 34 : 32,
  radius: id === 'pip-tools' ? 12 : id === 'account-menu' ? 17 : 8, source: 'ddm/' + file,
  row, sheet: 'application', area: 'settings',
  group: row < 9 || (row >= 36 && row < 38) ? '添加与关注'
    : (row < 22 || (row >= 38 && row < 42)) ? '画面墙与播放' : '系统与设置',
}));

const labSkinScenes = [
  [
    [10,10,154,500,'关注栏','sidebar'], [19,18,102,25,'DD监控室CE'], [130,18,25,25,'«','buttons'],
    [19,51,40,25,'排序','buttons'], [72,51,40,25,'◐','buttons'], [114,51,40,25,'↻','buttons'],
    [19,86,136,29,'文件夹 · 3','sidebar'], ...[125,223,321].map(y => [23,y,128,85,'关注卡片']),
    [19,425,82,29,'布局预设','buttons'], [107,425,48,29,'设置','buttons'],
    [19,465,62,29,'导入关注','buttons'], [87,465,68,29,'添加直播间','buttons'],
    ...[[176,10,405,324],[591,10,199,157],[591,177,199,157],[176,344,199,166],[384,344,197,166],[591,344,199,166]]
      .flatMap(([x,y,w,h]) => [[x,y,w,h,'直播画面'],[x+2,y+h-33,w-4,31,'Ⅱ　◖　弹幕　⛶','controls']]),
  ],
  [
    [25,20,750,480,'','settings'], [36,34,155,452,'分类','sidebar'], [207,34,550,388,'内容区','settings'],
    ...['常规','外观','弹幕','录制','快捷键','插件'].map((label,i) => [47,53+i*49,132,34,label]),
    ...['设置页面','颜色模式','背景与美化','常规设置'].map((label,i) => [227,60+i*55,505,35,label]),
    [535,442,100,32,'取消','buttons'], [646,442,100,32,'保存','buttons'],
  ],
  [
    [30,60,460,390,'对话框','settings'], [55,84,410,40,'添加直播间／导入关注'],
    [55,155,410,40,'房间号或直播间链接'], [55,215,410,40,'选择文件夹'],
    [520,60,245,130,'菜单','controls'], [530,77,225,31,'右键菜单'], [530,114,225,31,'账号菜单'],
    [520,205,245,130,'布局预设／直播间组合','settings'], [520,355,245,95,'提示','buttons'],
  ],
];
const labLayoutOptions = {
  普通布局: [['单画面','1'],['上下两分','1 2'],['左右两分','1,2'],['四分','1,2 3,4']],
  弹幕布局: [['主画面 + 弹幕','1,d'],['上 1 大 + 小 + 弹幕','1,1 2,d'],
    ['主画面 + 1 小 + 弹幕','1,2,d'],['主画面 + 2 小 + 弹幕','1,2,d 1,3,d']],
  竖屏布局: [['主画面 + 2 小','1,1 2,3'],['主画面 + 4 小','1,1 2,3 4,5'],
    ['主画面 + 6 小','1,1 2,3 4,5 6,7'],['主画面 + 2 小 + 弹幕','1,1 2,3 d,d']],
};

function labLayoutSwatch(spec) {
  const rows = spec.split(' ').map(row => row.split(','));
  const grid = rows.map(row => '"' + row.map(cell => 'tile' + cell).join(' ') + '"').join(' ');
  return `<div class="lab-qt-layout-swatch" style='grid-template-areas:${grid}' aria-hidden="true">
    ${[...new Set(rows.flat())].map(cell => `<i style="grid-area:tile${cell}" ${cell === 'd' ? 'class="lab-qt-layout-chat"' : ''}></i>`).join('')}</div>`;
}

function labSkinScene(regions, scene) {
  return `<div class="lab-qt-skin-scene" data-app-skin-scene="${scene}" ${scene ? 'hidden' : ''}>
    ${regions.map(([x,y,w,h,label,part]) => {
      const style = `left:${x / 8}%;top:${y * 100 / 520}%;width:${w / 8}%;height:${h * 100 / 520}%`;
      return part
        ? `<button type="button" class="lab-control" style="${style}" aria-label="${label || '设置窗口'}" title="${label || '设置窗口'}" data-app-action="skin-part"
          data-app-part="${part}" aria-pressed="${label === '关注栏'}"><span class="lab-label">${label}</span></button>`
        : `<span class="lab-qt-skin-static" aria-hidden="true" style="${style}">${label}</span>`;
    }).join('')}</div>`;
}

function labAppExample(item, popupId) {
  const b = (text, action, primary = false, glyph = '') =>
    labButton(text, glyph, glyph ? '' : text, `data-app-action="${action}"`, primary);
  const avatar = (name, action, primary = false) =>
    labButton(name, '', name[0], `data-app-action="${action}" aria-pressed="false"`, primary);
  const field = (label, type = 'text', attrs = '') =>
    `<input class="lab-control lab-app-field" type="${type}" aria-label="${label}" ${attrs}>`;
  const check = (label, checked = false, attrs = '') =>
    `<label class="lab-app-check"><input type="checkbox" ${checked ? 'checked' : ''} ${attrs}>${label}</label>`;
  const toggle = (label, checked, attrs = '') =>
    `<label class="lab-app-switch"><span>${label}</span><span class="lab-switch"><input type="checkbox" role="switch"
      aria-label="${label}" ${checked ? 'checked' : ''} ${attrs}><span class="lab-track"></span></span></label>`;
  const choice = (values, key = '', selected = 0) =>
    `<div class="lab-app-choice" role="group" aria-label="${key || item.title}">${values.map((label,index) =>
      labButton(label, '', label, `aria-pressed="${index === selected}" data-app-choice="${key || label}"`, index === 0)).join('')}</div>`;
  const select = (values, label) => labSelect(label, values);
  const dialog = (trigger, title, body) =>
    `${b(trigger, 'open', true)}<dialog class="lab-color-dialog lab-app-dialog" aria-label="${title}">
      <h3>${title}</h3>${body}</dialog>`;
  const popupButton = (label, body, glyph = '') =>
    `${labButton(label, glyph, glyph ? '' : label, `popovertarget="${popupId}"`, true)}
      <div class="lab-extra-popup lab-app-popup" id="${popupId}" popover aria-label="${label}">${body}</div>`;
  const line = (label, control) => `<div class="lab-app-line"><span>${label}</span>${control}</div>`;
  const roomRows = `<div class="lab-qt-room-grid">
    <button class="lab-app-row lab-control" data-app-action="room" data-app-find="小岚 xiaolan xl 10001" data-app-live><i>小</i><span>小岚</span></button>
    <button class="lab-app-row lab-control" data-app-action="room" data-app-find="阿海 ahai ah 10002"><i>阿</i><span>阿海</span></button>
    <small data-app-empty hidden>没有匹配的关注</small></div>`;
  const importRow = (name, caption, checked, disabled = false) => `<label class="lab-app-check lab-qt-import-row">
    <i class="lab-app-avatar">${name[0]}</i><span><strong>${name}</strong><small>${caption}</small></span>
    <input type="checkbox" aria-label="${name}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : 'data-app-import'}></label>`;
  const sectionHead = (title, close = '') => `<header class="lab-qt-section-head"><strong>${title}</strong>${close}</header>`;
  const searchBox = label => field(label, 'search', `placeholder="${label}" data-app-search data-primary`);
  const panes = (count, selectAction = '') => `<div class="lab-app-panes" style="--pane-columns:${count === 4 ? 2 : count}">
    ${Array.from({length:count}, (_, i) => selectAction
      ? `<button class="lab-control" type="button" draggable="true" data-app-action="${selectAction}" aria-pressed="${i === 0}">${['小岚','阿海','星河','画面 4'][i]}</button>`
      : '<span></span>').join('')}</div>`;
  let html;
  switch (item.id) {
    case 'room-search':
      html = searchBox('搜索关注主播 / 房间号') + `<div data-app-search-results hidden>${roomRows}</div>`; break;
    case 'room-add':
      html = `<div class="lab-qt-inline-add" data-app-room-editor>
        <div class="lab-qt-inline-entry"><textarea class="lab-app-field" rows="2" aria-label="房间号或链接" placeholder="房间号或链接，每行一个" data-app-room-input data-primary>10001</textarea>
          ${b('关闭添加','room-editor-close',false,'close')}</div>
        <small class="lab-qt-error" data-app-room-error hidden></small>
        <div class="lab-app-choice">${select(['默认分组','收藏'], '添加到文件夹')}${b('导入关注','report',false,'update')}${b('添加 1 个','room-add')}</div>
        </div><div data-app-room-reopen hidden>${b('添加直播间','room-editor-open')}</div>`; break;
    case 'room-picker':
      html = `<div class="lab-app-choice lab-qt-room-filter">${searchBox('搜索关注主播 / 房间号')}${check('直播中', false, 'data-app-filter-live')}</div>
        <small class="lab-qt-room-group">默认分组</small>${roomRows}`; break;
    case 'follow-import':
      html = `<div class="lab-qt-portal">${sectionHead('导入关注')}${choice(['哔哩哔哩','其他平台'])}<div class="lab-app-stack">
        ${importRow('小岚','直播中 · 午后直播',true)}${importRow('阿海','未开播 · 聊天',false)}
        ${importRow('星河','已关注',true,true)}</div><div class="lab-qt-actions">${b('导入所选','import',true)}</div></div>`; break;
    case 'follow-card':
      html = `<label class="lab-app-follow" data-primary><input type="checkbox" checked aria-label="选中小岚">
        <span><strong>小岚</strong><small>午后直播</small></span><span class="lab-qt-card-foot">${labIcon('qt-bili')}<small>直播中</small></span></label>`; break;
    case 'folder-head':
      html = `<div class="lab-app-choice lab-qt-folder-head">${labButton('默认分组','folder','默认分组',
        'data-app-action="folder-toggle" aria-expanded="true"',true)}${b('重命名','folder-name',false,'more')}</div>
        ${field('文件夹名称','text','data-app-folder-edit hidden')}<div data-app-folder-content>${roomRows}</div>`; break;
    case 'folder-edit':
      html = dialog('编辑文件夹','修改文件夹图标', `<div class="lab-qt-icon-current"><span>${labIcon('folder')}</span>
        ${field('文件夹名称','text','value="默认分组" data-app-value')}</div>
        <small>内置图标</small><div class="lab-qt-icon-grid">${[['文件夹','folder'],['星标','star'],['爱心','heart'],
          ['游戏','game'],['音乐','music'],['视频','qt-tabs']].map(([label,glyph],i) =>
          labButton(label,glyph,label,`data-app-action="folder-icon" data-app-folder-glyph="${glyph}" aria-pressed="${i===0}"`)).join('')}</div>
        <div class="lab-app-choice">${labPresets.slice(1).map(([color,label]) =>
          `<button type="button" class="lab-control lab-swatch-dot" style="--swatch:${color}" aria-label="${label}" data-app-action="folder-color" data-app-color="${color}"></button>`).join('')}</div>
        ${line('自定义颜色',field('图标颜色','color','value="#00a1d6" data-app-folder-color'))}
        <div class="lab-qt-actions">${b('恢复默认','folder-reset')}${b('取消','cancel')}${b('保存','save')}</div>`)
        + `<div class="lab-app-folder-preview"><span aria-hidden="true">${labIcon('folder')}</span><span>默认分组</span></div>`; break;
    case 'function-hub':
      html = popupButton('功能中心', `${sectionHead('功能中心',b('关闭功能中心','popup-close',false,'close'))}${searchBox('搜索功能、插件')}
        <small data-app-count>2 / 2 个功能 · 可固定常用入口到侧栏</small>
        <div class="lab-qt-hub-row" data-app-find="插件商店 chajianshangdian cjsd">${b('插件商店 / 管理插件','report')}${b('固定为常用','toggle',false,'pin')}</div>
        <div class="lab-qt-hub-row" data-app-find="插件功能 chajiangongneng cjgn">${b('插件功能','report')}${b('固定为常用','toggle',false,'pin')}</div>
        <small data-app-empty hidden>没有匹配的功能</small>`, 'qt-grid'); break;
    case 'account-menu':
      html = `<button class="lab-control lab-qt-account" type="button" data-primary data-lab-glyph="qt-bili" popovertarget="${popupId}" aria-label="示例账号">
          <span class="lab-app-avatar">示</span><span><strong>示例账号</strong><small>ID: 10001</small></span>
          <span class="lab-glyph" data-icon-slot>${labIcon('qt-bili')}</span><span aria-hidden="true">›</span></button>
        <div class="lab-extra-popup lab-app-popup" id="${popupId}" popover aria-label="账号菜单">
        ${b('选择平台并登录','report')}${b('退出登录','report')}</div>`; break;
    case 'layout-picker':
      html = `<div class="lab-qt-portal">${sectionHead('布局预设','<small data-app-layout-current>当前：单画面</small>')}
        ${choice(['普通布局','弹幕布局','竖屏布局'],'布局分类')}
        <small class="lab-qt-room-group" data-app-layout-group>均分</small>
        <div class="lab-app-choice lab-layouts">${labLayoutOptions.普通布局.map(([label,spec],index) =>
          `<button class="lab-control lab-layout-card" data-app-choice="layout" aria-label="${label}" aria-pressed="${index===0}" ${index ? '' : 'data-primary'}>${labLayoutSwatch(spec)}<span>${label}</span></button>`).join('')}</div>
        <div class="lab-qt-actions">${b('恢复默认比例','layout-reset')}</div></div>`; break;
    case 'room-preset':
      html = `<div class="lab-qt-preset-head"><small>保存布局、主播位置和每格声音</small>${b('保存当前组合…','open',true)}</div>
        <div class="lab-qt-preset-form" data-app-preset-form hidden>${line('组合名称',field('组合名称','text','placeholder="输入名称" data-app-value'))}
        ${b('保存','save')}${b('取消','cancel')}</div><p class="lab-qt-preset-list" data-app-preset-list>尚未保存直播间组合</p>`; break;
    case 'wall-remove':
      html = `<div class="lab-qt-portal">${sectionHead('移除画面')}<small>双画面 · 点击格子选择移除</small>
        <div class="lab-qt-removal-panes">${check('小岚 · 直播中',false,'data-app-pane')}${check('阿海 · 未开播',false,'data-app-pane data-app-offline')}</div>
        ${choice(['选择未开播','选择全部直播','取消选择'],'remove-scope', -1)}
        <small data-app-selection>已选 0 路 · 移除后保留空位及关注列表</small>
        <div class="lab-qt-actions">${b('撤回上次移除','undo')}${b('移除所选','remove',true)}</div></div>`; break;
    case 'wall-quick':
      html = `<div class="lab-qt-portal">${line('整体音量',labRange('整体音量',0,100,48,'',true))}
        ${line('画质',select(['选择画质','原画','超清 720P','流畅'], '画质'))}${toggle('画面弹幕',false)}${toggle('弹幕浮窗',false)}</div>`; break;
    case 'pip-composer':
      html = choice(['一列','两列'],'pip-columns',1) + panes(2,'pip-primary'); break;
    case 'pip-tools':
      html = `<div class="lab-app-choice">${b('选择画面组合','report',true,'qt-grid')}${b('调整画面位置','toggle',false,'qt-swap')}
        ${b('置顶画中画','toggle',false,'pin')}${b('返回监控室','report',false,'qt-return')}${b('关闭画中画','report',false,'close')}</div>`; break;
    case 'pip-audio':
      html = `<div class="lab-app-choice lab-qt-audio-row"><span class="lab-app-avatar" title="小岚">小</span>
        ${b('小岚静音','mute',true,'qt-volume')}${labRange('小岚音量',0,100,40,'%')}</div>`; break;
    case 'volume-popup':
      html = popupButton('音量', `<div class="lab-app-vertical">${labRange('音量',0,100,40)}</div>`, 'qt-volume'); break;
    case 'stream-state':
      html = `<div class="lab-stream-status">${labIcon('qt-bili')}<span data-app-stream>连接中…</span></div>${select(['连接中…','缓冲中…','播放中','已暂停','播放失败','已下播'],'播放状态')}`; break;
    case 'stream-info':
      html = dialog('直播流信息','直播流信息', `<p>小岚 · 10001</p>
        <dl class="lab-app-stats">${[['播放状态','播放中'],['封装格式','flv'],['播放内核','libmpv'],
          ['视频信息','1920×1080 · 60 FPS · H.264'],['音频信息','AAC · 48 kHz · 立体声'],['流编码器','未知'],
          ['流服务器','示例'],['缓冲长度','2 秒'],['解码统计','60 FPS · 丢帧 0 / 0'],['视频码率','5 Mbps'],
          ['下载速率','5.2 Mbps']].map(([term,value]) => `<dt>${term}</dt><dd>${value}</dd>`).join('')}</dl>
        <div class="lab-qt-actions">${b('关闭','cancel')}</div>`); break;
    case 'caption-tools':
      html = `<div class="lab-app-choice lab-qt-caption-tools">
        ${b('字幕显示内容','caption-mode',true,'qt-caption')}${b('减小字号','caption-smaller',false,'minus')}
        ${b('增大字号','caption-larger',false,'plus')}${b('恢复位置与大小','caption-reset',false,'refresh')}${b('锁定字幕位置','toggle',false,'qt-lock')}</div><p data-app-caption>字幕预览</p>`; break;
    case 'danmaku-panel':
      html = `<div class="lab-qt-chat"><header class="lab-qt-chat-head"><strong><i></i>弹幕</strong>${labRange('弹幕字号',8,32,13,'',true)}
        ${b('跟随新弹幕','follow-comments',false,'qt-live')}</header>
        <div class="lab-app-comments" data-app-comments tabindex="0">小岚：晚上好<br>阿海：欢迎来到直播间</div>
        <div class="lab-qt-chat-footer">${field('输入示例弹幕','text','placeholder="弹幕内容" data-app-value')}${b('回到底部','bottom',false,'down')}</div></div>`; break;
    case 'super-chat':
      html = `<article class="lab-app-sc" data-app-sc><div class="lab-app-sc-head"><span class="lab-app-avatar" aria-hidden="true">小</span>
        <span>小岚<strong>¥30</strong></span><small>剩 0:30</small>${b('展开／收起','sc-toggle',true,'down')}${b('关闭','sc-close',false,'close')}</div>
        <p>感谢直播，今天也很开心！</p></article>${b('恢复示例','sc-restore')}`; break;
    case 'shortcut-edit':
      html = `<div class="lab-app-shortcut"><label for="${popupId}-key">静音</label><div class="lab-qt-key-field">
        ${field('静音快捷键','text',`id="${popupId}-key" value="M" readonly data-app-shortcut data-primary`)}
        ${b('清除快捷键','shortcut-clear',false,'close')}</div>${toggle('启用',true,'data-app-shortcut-enable')}${b('恢复','shortcut-reset')}</div>`; break;
    case 'settings-caption':
      html = `<div class="lab-qt-titlebar" data-app-title><strong>设置</strong>${b('关闭设置','settings-close',true,'close')}</div>
        <div data-app-title-closed hidden>${b('重新打开设置','settings-restore')}</div>`; break;
    case 'close-choice':
      html = dialog('关闭窗口','关闭窗口', `<p>关闭窗口后，你希望程序如何运行？</p>
        <p class="lab-qt-hint">隐藏后的播放行为可在设置 → 托盘行为中调整，录制会继续运行。双击托盘图标可恢复窗口。</p>
        <div class="lab-qt-actions">${check('记住我的选择',false,'data-app-remember')}
        ${labButton('隐藏到托盘','','隐藏到托盘','data-app-action="close-choice" data-lab-primary-tone autofocus')}${b('退出程序','close-choice')}</div>`); break;
    case 'cache-pie':
      html = `<div class="lab-app-cache"><button type="button" class="lab-control" data-primary data-app-action="cache-segment" aria-label="图片缓存占用饼图">
        <strong>100.0 MB</strong><small>合计</small></button><div>
        ${check('头像 75 MB',false,'data-app-cache')}${check('封面 25 MB',false,'data-app-cache')}
        ${b('清理所选','cache-clear')}</div></div>`; break;
    case 'skin-library':
      html = `<div class="lab-app-choice lab-qt-library">
        ${labButton('默认背景','qt-image-off','','data-app-choice="skin" aria-pressed="true"',true)}
        ${labButton('导入背景','update','','data-app-choice="skin" aria-pressed="false"')}
        </div>${field('导入背景文件','file','accept="image/*,video/*" data-app-skin hidden')}
        <div class="lab-app-skin-preview" data-app-skin-preview hidden>默认背景</div>`; break;
    case 'blocked-users':
      html = `<select size="3" class="lab-control lab-app-field" aria-label="已屏蔽用户" data-app-list><option>10001</option></select>
        <div class="lab-app-choice lab-qt-block-row">${select(['哔哩哔哩','虎牙','斗鱼'],'屏蔽用户所属平台')}
        ${field('用户 UID','text','placeholder="B站 UID（数字）" inputmode="numeric" data-app-value data-primary')}
        ${b('添加','block-add')}${b('移除所选','block-remove')}</div><small class="lab-qt-hint">仅检查格式，不查询账号资料。</small>`; break;
    case 'audio-response':
      html = `<svg viewBox="0 0 250 100" class="lab-app-response" aria-label="音量均衡时间响应曲线">
        <rect x="25" y="17" width="213" height="65" rx="4"/><path d="M25 24H238M25 48H238M25 72H238M78 17V82M130 17V82M183 17V82" class="lab-curve-grid"/>
        <text x="6" y="11">增益 dB</text><text x="10" y="28">0</text><text x="8" y="52">-3</text><text x="8" y="75">-6</text>
        <text x="25" y="94">0s</text><text x="127" y="94">8s</text><text x="218" y="94">16s</text>
        <path class="lab-curve-line"/>${['压低时间','保持时间','恢复时间'].map((label,i) =>
          `<circle r="4" tabindex="0" role="slider" aria-label="${label}" aria-valuemin="0" aria-valuemax="30" data-app-response-point="${i}"/>`).join('')}</svg>
        ${line('压低时间',field('压低时间（秒）','number','min=".1" max="30" step=".1" value="2" data-app-response-part'))}
        ${line('保持时间',field('保持时间（秒）','number','min="0" max="30" step=".1" value="2" data-app-response-part'))}
        ${line('恢复时间',field('恢复时间（秒）','number','min=".1" max="30" step=".1" value="8" data-app-response-part data-app-response data-primary'))}`; break;
    case 'menu-order':
      html = `<div class="lab-app-order" data-app-order>${['音量','画质','当前窗口编解码设置'].map((label,index) =>
        `<div draggable="true" class="lab-app-order-row" tabindex="0" aria-label="${label}，用 Alt 和方向键排序"><span aria-hidden="true">≡</span>
          ${toggle(label,true)}<div class="lab-qt-reorder-keys">${b('上移','up',index===0,'down')}${b('下移','down',false,'down')}</div></div>`).join('')}</div>`; break;
    case 'notices':
      html = popupButton('通知 · 1 条未读', `<header class="lab-qt-notice-head"><span>${labIcon('bell')}</span>
        <div><strong>通知</strong><small>本次启动 · 1 条</small></div>${b('清空通知','clear-notices',false,'qt-trash')}
        ${b('关闭通知','popup-close',false,'close')}</header><article class="lab-qt-notice-card" data-app-notice>
        <div><i></i><strong>开播提醒</strong><time>23:52</time>${b('删除这条通知','clear-notices',false,'close')}</div>
        <p>示例直播间开播了</p><div class="lab-qt-actions">${labButton('查看详情','','查看详情','data-app-action="read" data-lab-primary-tone')}</div></article>`, 'bell'); break;
    case 'update-notice':
      html = `<article class="lab-qt-notice-card" data-app-update><header class="lab-qt-update-head"><img src="${identity}" alt="">
        <div><strong>版本更新</strong><p>发现新版本</p><small>查看更新说明，选择是否安装。</small></div>
        ${b('关闭提醒','update-close',false,'close')}</header><div class="lab-qt-actions">${b('查看更新','report',true)}</div>
        </article><div data-app-update-closed hidden>${b('恢复提醒','update-restore')}</div>`; break;
    case 'tray-layout':
      html = `<button class="lab-control lab-app-tray" data-app-action="restore" aria-label="点击恢复主窗口" data-primary>
        <span class="lab-qt-tray-tiles"><span>视频 · 小岚</span><span>弹幕 · 弹幕</span></span><small>蓝：视频　粉：弹幕　灰：空格</small></button>`; break;
    case 'record-path':
      html = `<div class="lab-app-choice lab-app-path">${field('保存目录','text','value="C:/示例/录制" data-app-value data-primary')}
        ${b('浏览…','path')}</div>`; break;
    case 'diagnostic-form':
      html = `<select size="2" class="lab-control lab-app-field" aria-label="附加图片" data-app-list data-primary><option>示例截图.png</option></select>
        <div class="lab-app-choice">${b('添加图片','diagnostic-add')}${b('移除所选','list-remove')}</div>
        <div class="lab-qt-actions">${b('导出诊断包','diagnostic-export')}</div>`; break;
    case 'smart-folder':
      html = dialog('编辑智能文件夹','编辑智能文件夹', `${line('名称',field('智能文件夹名称','text','value="直播中" data-app-value'))}
        <div class="lab-app-line"><span>来源文件夹</span><details class="lab-qt-smart-source"><summary>默认分组</summary>
        <div class="lab-app-choice">${check('默认分组',true,'data-app-smart')}${check('收藏',false,'data-app-smart')}</div></details></div>
        ${line('显示方式',select(['匹配时移入显示，不匹配时回到原处','保留原处，同时在智能文件夹显示'],'显示方式'))}
        ${line('开播状态',select(['开播','未开播','全部状态'],'开播状态'))}
        ${line('卡片排序',select(['自定义','常看优先'],'卡片排序'))}
        <div class="lab-app-choice">${check('哔哩哔哩')}${check('虎牙')}${b('取消','cancel')}${b('保存','save')}</div>`); break;
    case 'account-platform':
      html = `<div class="lab-app-choice lab-qt-platforms" role="group" aria-label="账号平台">
        ${[['B站','platform-bili'],['虎牙','platform-huya'],['斗鱼','platform-douyu']].map(([name,glyph],index) =>
          labButton(name,glyph,name,`data-app-choice="账号平台" aria-pressed="${!index}"`,index===0)).join('')}</div>`; break;
    case 'danmaku-source':
      html = `<header class="lab-qt-chat-head lab-qt-source-head"><strong><i></i>弹幕</strong>
        ${labRange('弹幕字号',8,32,13,'',true)}${b('弹出弹幕栏','report',false,'panel')}
        ${popupButton('选择弹幕来源', `<div class="lab-app-choice lab-app-source">${avatar('小岚','source')}${avatar('阿海','source')}</div>`, 'qt-tabs')}
        ${b('跟随新弹幕','toggle',false,'qt-live')}</header>`; break;
    case 'comment-actions':
      html = popupButton('小岚：晚上好', `<div class="lab-app-choice">${b('复制','comment-copy')}${b('+1','report')}
        ${b('屏蔽弹幕','report')}${b('屏蔽用户','report')}</div>`); break;
    case 'danmaku-float':
      html = `<div class="lab-app-note" data-app-float-panel>弹幕 · 示例直播间<p>小岚：晚上好</p></div>
        ${b('弹幕浮窗','chat-float',true)}<div data-app-float-slot hidden>${b('收回弹幕栏','chat-return')}</div>`; break;
    case 'caption-placement':
      html = `<div class="lab-app-caption-stage"><button class="lab-control" type="button" data-primary
        data-app-caption-move aria-label="字幕位置，使用方向键移动"><small>今日はみんなとゲームを楽しみます。</small><span>今天和大家一起享受游戏。</span></button></div>
        ${labRange('字幕大小',10,24,14,' px')}${b('恢复位置与大小','caption-place-reset')}`; break;
    case 'theme-editor':
      html = `<div class="lab-app-choice lab-swatches" role="group" aria-label="主题色">${labPresets.map(([color, label],index) => `
        <button type="button" class="lab-control ${index ? 'lab-swatch-dot' : ''}" aria-label="${label}" title="${label}"
          aria-pressed="${index === 0}" data-app-choice="主题色" data-app-color="${color}"
          ${index ? `style="--swatch:${color}"` : ''}>${index ? '' : label}</button>`).join('')}</div>
        ${line('自定义色值',field('自定义色值','text','placeholder="#RRGGBB" maxlength="7" data-app-theme-color data-primary'))}
        ${line('界面字体',select(['系统默认','微软雅黑','等宽字体'],'界面字体'))}
        ${line('界面字号',`<span class="lab-qt-number-step">${b('减小界面字号','theme-size-down',false,'minus')}
        ${field('界面字号','number','min="11" max="20" value="13" data-app-theme-size')}<span>px</span>
        ${b('增大界面字号','theme-size-up',false,'plus')}</span>`)}
        <div class="lab-app-note" data-app-theme-sample>关注列表 · 示例主播</div>`; break;
    case 'skin-parts':
      html = `${select(['主界面','设置页面','布局预设'],'预览场景')}
        <div data-app-skin-areas>${labSkinScenes.map(labSkinScene).join('')}</div>
        ${line('分区底色',field('分区底色','color','value="#007ba8" data-app-part-color'))}`; break;
    case 'notice-blur':
      html = `<div class="lab-app-blur" data-app-blur data-banner="true"><span></span><p>开播提醒<br>示例主播开播了</p></div>
        ${toggle('使用直播封面',true,'data-app-banner')}${labRange('模糊程度',0,32,16)}`; break;
    case 'streamer-profile':
      html = `<div class="lab-qt-portal lab-qt-profile"><div class="lab-qt-profile-head">
        ${labButton('展开主播设置','down','','data-app-action="profile-expand" aria-expanded="false"',true)}
        <span class="lab-qt-profile-avatars lab-app-source">${avatar('小岚','profile-room')}${avatar('阿海','profile-room')}</span>
        <span data-app-profile>编辑整组 · 2 位主播</span>${b('移除设置','profile-remove')}</div>
        <div class="lab-qt-profile-summary" data-app-profile-summary>
        ${[['播放画质','play','继承'],['录制画质','circle','继承'],['音量','volume','40%']].map(([label,glyph,value]) =>
          `<span title="${label}">${labIcon(glyph)}<output>${value}</output></span>`).join('')}</div>
        <div class="lab-qt-profile-form" data-app-profile-form hidden>
          ${line('默认播放画质',select(['继承','原画','超清 720P'],'默认播放画质'))}
          ${line('录制画质',select(['继承','原画','超清 720P'],'录制画质'))}
          ${line('默认音量',field('默认音量','number','min="-1" max="100" value="40" data-app-profile-volume'))}
          <div class="lab-qt-actions">${b('刷新画质','profile-refresh')}</div></div></div>`; break;
    case 'startup-notice':
      html = dialog('阅读用户须知','用户须知', `<div class="lab-app-reading" tabindex="0">
        <p>欢迎使用 <strong>DD监控室CE</strong>。使用前，请阅读以下说明。</p>
        <strong>1. 开源与免费</strong><p>本软件是一款免费、开源的软件，遵循 GNU LGPL 2.1 开源许可证。</p>
        <strong>2. 官方获取渠道</strong><p>请通过项目官方发布页面获取软件及更新。</p>
        <strong>3. 第三方平台与插件</strong><p>本软件独立于第三方直播平台。登录和安装插件前请了解来源和权限。</p>
        <strong>4. 使用与反馈</strong><p>请遵守平台规则，尊重主播及其他权利人的权益。</p></div>
        <div class="lab-qt-actions">${b('我已阅读并确认','notice-confirm')}</div>`); break;
    case 'settings-material':
      html = `<div class="lab-qt-portal">${sectionHead('视觉效果')}
        ${toggle('启用毛玻璃效果',false,'data-app-glass')}<small class="lab-qt-hint">底色不透明度在开启时生效。</small>
        <div data-app-opacity hidden>${line('底色不透明度',labRange('底色不透明度',0,100,70,'%'))}</div>
        ${toggle('禁用卡片与控件阴影',false,'data-app-no-shadows')}
        ${line('设置卡片布局',select(['自动','单列','双列'],'设置卡片布局'))}</div>
        <div class="lab-app-material" data-app-material data-glass="false" data-shadows="true" data-columns="自动">
        <span>常规</span><span>外观</span></div>
        ${labChoice('设置分类', [['general','常规'],['appearance','外观']])}`; break;
    case 'plugin-remove':
      html = dialog('删除插件','删除这个插件？', `<p>将删除插件“示例插件”及其文件。<br>已加载的插件将在重启后停止运行。</p>
        <div class="lab-qt-actions">${labButton('取消','','取消','data-app-action="cancel" autofocus')}${b('删除','delete')}</div>`);
  }
  return `<div class="lab-app">${html}</div>`;
}
function labBindApplication(host, item, report, paintIcon) {
  const demo = host.querySelector('.lab-app');
  const select = selector => demo.querySelector(selector);
  const all = selector => [...demo.querySelectorAll(selector)];
  const toggle = button => {
    const selected = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', selected);
    return selected;
  };
  const text = button => button.getAttribute('aria-label') || button.textContent.trim();
  const setLabel = (button, value) => {
    button.querySelector('.lab-label').textContent = value;
    button.setAttribute('aria-label', value);
    button.title = value;
  };
  const move = (row, destination, after = false) => {
    if (!destination || row === destination) return;
    destination[after ? 'after' : 'before'](row);
    report('已调整顺序');
  };
  let lastRemoved = [];
  let captionSize = 16;
  let dragged;
  const popupTrigger = select('button[popovertarget]');
  if (item.id === 'notices') popupTrigger.dataset.appUnread = 'true';
  const curve = select('.lab-app-response');
  const responseFields = all('[data-app-response-part]');
  function updateResponse() {
    const [attack,hold,release] = responseFields.map(field => Number(field.value));
    const x = time => 25 + 213 * time / Math.max(16,attack+hold+release+2);
    const a = x(attack), h = x(attack+hold), r = x(attack+hold+release);
    curve.querySelector('.lab-curve-line').setAttribute('d', `M25 24 C${x(attack*.25)} 64 ${x(attack*.5)} 71 ${a} 72 H${h} C${x(attack+hold+release*.18)} 42 ${x(attack+hold+release*.48)} 29 ${r} 26 L238 24`);
    all('[data-app-response-point]').forEach((point,index) => {
      point.setAttribute('cx',[a,h,r][index]);
      point.setAttribute('cy',index===2 ? '26' : '72');
      point.setAttribute('aria-valuenow',responseFields[index].value);
    });
  }
  if (curve) {
    all('[data-app-response-point]').forEach((point,index) => {
      const field = responseFields[index];
      let start;
      const set = value => {
        field.value = Math.max(Number(field.min),Math.min(Number(field.max),Math.round(value*10)/10));
        field.dispatchEvent(new Event('input',{bubbles:true}));
      };
      point.addEventListener('pointerdown',event => {
        point.setPointerCapture(event.pointerId);
        start = [event.clientX,Number(field.value)];
      });
      point.addEventListener('pointermove',event => {
        if (point.hasPointerCapture(event.pointerId)) set(start[1] + (event.clientX-start[0]) * 20 / curve.getBoundingClientRect().width);
      });
      point.addEventListener('keydown',event => {
        if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        set(Number(field.value) + (event.key==='ArrowRight' ? .1 : -.1));
      });
    });
    updateResponse();
  }
  const caption = select('[data-app-caption-move]');
  const skinAreas = select('[data-app-skin-areas]');
  const material = select('[data-app-material]');
  const cache = select('.lab-app-cache');
  if (cache) {
    cache.addEventListener('input', () => {
      cache.dataset.selected = all('[data-app-cache]').map(check => check.checked ? '1' : '0').join('');
    });
  }
  const folderColor = select('[data-app-folder-color]');
  const presetForm = select('[data-app-preset-form]');
  const profileForm = select('[data-app-profile-form]');
  const profileValues = profileForm ? {小岚: ['继承','继承','40'], 阿海: ['继承','继承','-1']} : null;
  let profileRoom;
  const profileFields = () => [...profileForm.querySelectorAll('select,input')];
  function showProfile(expanded) {
    profileForm.hidden = !expanded;
    select('[data-app-profile-summary]').hidden = expanded;
    const button = select('[data-app-action=profile-expand]');
    button.setAttribute('aria-expanded', expanded);
    button.setAttribute('aria-label', expanded ? '收起主播设置' : '展开主播设置');
    button.title = button.getAttribute('aria-label');
    const values = profileValues[profileRoom || '小岚'];
    profileFields().forEach((field,index) => { field.value = values[index]; });
    all('[data-app-profile-summary] output').forEach((output,index) => {
      output.value = index === 2 ? (values[index] === '-1' ? '继承' : values[index] + '%') : values[index];
    });
  }
  const updateSelection = () => {
    const count = all('[data-app-pane]:checked').length;
    const summary = select('[data-app-selection]');
    if (summary) {
      summary.textContent = `已选 ${count} 路 · 移除后保留空位及关注列表`;
      const remove = select('[data-app-action=remove]');
      setLabel(remove, count ? `移除所选 ${count} 路` : '移除所选');
      remove.disabled = count === 0;
    }
  };
  let folderGlyph = 'folder';
  let skinPart;
  if (caption) {
    const stage = caption.parentElement;
    let position = [50, 78];
    const place = (x, y) => {
      position = [Math.max(12, Math.min(88, x)), Math.max(14, Math.min(86, y))];
      caption.style.left = position[0] + '%';
      caption.style.top = position[1] + '%';
    };
    caption.addEventListener('pointerdown', event => {
      if (event.button === 0) caption.setPointerCapture(event.pointerId);
    });
    caption.addEventListener('pointermove', event => {
      if (!caption.hasPointerCapture(event.pointerId)) return;
      const bounds = stage.getBoundingClientRect();
      place((event.clientX - bounds.left) * 100 / bounds.width, (event.clientY - bounds.top) * 100 / bounds.height);
    });
    caption.addEventListener('keydown', event => {
      const offset = {ArrowLeft: [-4,0], ArrowRight: [4,0], ArrowUp: [0,-4], ArrowDown: [0,4]}[event.key];
      if (!offset) return;
      event.preventDefault();
      place(position[0] + offset[0], position[1] + offset[1]);
    });
    const reset = () => {
      place(50, 78);
      caption.style.removeProperty('font-size');
      const slider = select('input[type=range]');
      slider.value = 14;
      slider.dispatchEvent(new Event('input', {bubbles:true}));
      report('已恢复字幕位置与大小');
    };
    caption.addEventListener('dblclick', reset);
    select('[data-app-action=caption-place-reset]').addEventListener('click', reset);
  }

  function clearUnread() {
    popupTrigger.dataset.appUnread = 'false';
    popupTrigger.setAttribute('aria-label', '通知（本次启动）');
    popupTrigger.title = '通知（本次启动）';
  }

  function filter() {
    const query = (select('[data-app-search]')?.value || '').toLowerCase().trim();
    const terms = query.split(/\s+/);
    const live = select('[data-app-filter-live]')?.checked;
    const rows = all('[data-app-find]');
    rows.forEach(row => { row.hidden = !terms.every(term => row.dataset.appFind.includes(term)) || Boolean(live && !row.hasAttribute('data-app-live')); });
    const empty = select('[data-app-empty]');
    if (empty) empty.hidden = rows.some(row => !row.hidden);
    const results = select('[data-app-search-results]');
    if (results) results.hidden = !query;
    const count = select('[data-app-count]');
    if (count) count.textContent = `${rows.filter(row => !row.hidden).length} / ${rows.length} 个功能 · 可固定常用入口到侧栏`;
  }

  function updateRooms() {
    const unique = [...new Set(select('[data-app-room-input]').value.split(/\n/).map(line => line.trim()).filter(Boolean))];
    const button = select('[data-app-action="room-add"]');
    setLabel(button, unique.length ? `添加 ${unique.length} 个` : '添加');
    button.disabled = !unique.length;
    select('[data-app-room-error]').hidden = true;
    return unique;
  }

  function changeCaption(action) {
    const view = select('[data-app-caption]');
    if (action === 'caption-mode') {
      const labels = ['字幕预览','仅显示译文','显示原文与译文'];
      view.textContent = labels[(labels.indexOf(view.textContent) + 1) % labels.length];
    }
    if (action === 'caption-smaller') captionSize = Math.max(10, captionSize - 2);
    if (action === 'caption-larger') captionSize = Math.min(64, captionSize + 2);
    if (action === 'caption-reset') { captionSize = 16; view.textContent = '字幕预览'; }
    view.style.fontSize = captionSize + 'px';
    report(view.textContent + ' · ' + captionSize + ' px');
  }

  function addListValue(value) {
    const list = select('[data-app-list]');
    if ([...list.options].some(option => option.text === value)) { report('已存在'); return; }
    list.add(new Option(value, value, true, true));
    report('已添加 ' + value);
  }

  function clearSelected() {
    const list = select('[data-app-list]');
    if (list.selectedIndex < 0) { report('请选择一项'); return; }
    const value = list.options[list.selectedIndex].text;
    list.remove(list.selectedIndex);
    report('已移除 ' + value);
  }

  demo.addEventListener('input', ({target}) => {
    if (target.matches('[data-app-search],[data-app-filter-live]')) filter();
    if (target.matches('[data-app-room-input]')) updateRooms();
    if (target.matches('[data-app-smart]')) {
      const selected = all('[data-app-smart]:checked');
      select('.lab-qt-smart-source summary').textContent = selected.length > 1
        ? `已选择 ${selected.length} 个文件夹`
        : selected[0]?.closest('label').textContent.trim() || '全部关注';
    }
    if (profileForm?.contains(target) && target.validity.valid && target.value !== '') {
      const index = profileFields().indexOf(target);
      for (const name of profileRoom ? [profileRoom] : Object.keys(profileValues)) profileValues[name][index] = target.value;
    }
    if (target.type === 'range') {
      target.style.setProperty('--lab-level', `${(target.value - target.min) * 100 / (target.max - target.min)}%`);
      const output = target.nextElementSibling;
      output.textContent = target.value + output.dataset.unit;
      report(`${target.getAttribute('aria-label')} ${output.value}`);
      if (item.id === 'danmaku-panel') select('[data-app-comments]').style.fontSize = target.value + 'px';
      if (caption) caption.style.fontSize = target.value + 'px';
      if (item.id === 'notice-blur') select('[data-app-blur]').style.setProperty('--lab-blur', target.value / 3 + 'px');
      if (material) material.style.setProperty('--lab-opacity', target.value + '%');
    } else if (target.tagName === 'SELECT' && target.matches('.lab-select')) {
      const stream = select('[data-app-stream]');
      if (stream) stream.textContent = target.value;
      if (material) material.dataset.columns = target.value;
      if (item.id === 'theme-editor') {
        const fonts = ['inherit','"Microsoft YaHei UI", sans-serif','monospace'];
        select('[data-app-theme-sample]').style.fontFamily = fonts[target.selectedIndex];
      }
      if (skinAreas) {
        [...skinAreas.children].forEach((scene,index) => { scene.hidden = index !== target.selectedIndex; });
        skinPart = null;
      }
      report('已选 ' + target.value);
    } else if (target.matches('[data-app-shortcut-enable]')) {
      select('[data-app-shortcut]').disabled = !target.checked;
      report(target.checked ? '已启用快捷键' : '已禁用快捷键');
    } else if (target.type === 'checkbox' && !target.hasAttribute('data-app-filter-live')) {
      if (target.matches('[data-app-banner]')) select('[data-app-blur]').dataset.banner = target.checked;
      if (target.matches('[data-app-glass]')) {
        material.dataset.glass = target.checked;
        select('[data-app-opacity]').hidden = !target.checked;
      }
      if (target.matches('[data-app-no-shadows]')) material.dataset.shadows = !target.checked;
      report((target.checked ? '已选 ' : '已取消 ') + (target.getAttribute('aria-label') || target.closest('label')?.textContent.trim() || ''));
    }
    if (target.matches('[data-app-response-part]') && target.validity.valid && target.value) {
      updateResponse();
      report(target.getAttribute('aria-label') + ' ' + target.value + ' 秒');
    }
    if (target.matches('[data-app-folder-color]')) {
      select('.lab-qt-icon-current > span').style.color = target.value;
      report('图标颜色 ' + target.value.toUpperCase());
    }
    if (target.matches('[data-app-part-color]') && skinPart) {
      skinPart.style.setProperty('--lab-surface', target.value);
      report(text(skinPart) + '底色 ' + target.value.toUpperCase());
    }
    if (target.matches('[data-app-theme-color]')) {
      const value = target.value.trim();
      if (!value || /^#[\da-f]{6}$/i.test(value)) {
        select('[data-app-theme-sample]').style.borderColor = value;
        all('[data-app-color]').forEach(swatch => swatch.setAttribute('aria-pressed', swatch.dataset.appColor === value.toLowerCase()));
        report(value ? '主题色 ' + value.toUpperCase() : '使用默认主题色');
      } else report('请输入六位 HEX 色值');
    }
    if (target.matches('[data-app-theme-size]') && target.validity.valid && target.value)
      select('[data-app-theme-sample]').style.fontSize = target.value + 'px';
  });

  demo.addEventListener('change', ({target}) => {
    if (!target.matches('[data-app-skin]') || !target.files[0]) return;
    const url = URL.createObjectURL(target.files[0]);
    const video = target.files[0].type.startsWith('video/');
    const media = video ? document.createElement('video') : new Image();
    media.addEventListener(video ? 'loadeddata' : 'load', () => URL.revokeObjectURL(url), {once:true});
    media.addEventListener('error', () => URL.revokeObjectURL(url), {once:true});
    media.src = url;
    if (video) { media.controls = true; media.muted = true; }
    else media.alt = '导入的本地背景预览';
    const preview = select('[data-app-skin-preview]');
    preview.replaceChildren(media);
    preview.hidden = false;
    report('已更新试样背景');
    target.value = '';
  });

  demo.addEventListener('keydown', event => {
    const field = event.target;
    if (field.matches('[data-app-shortcut]') && !['Tab','Escape','Control','Shift','Alt','Meta'].includes(event.key)) {
      event.preventDefault();
      field.value = [event.ctrlKey && 'Ctrl', event.altKey && 'Alt', event.shiftKey && 'Shift', event.metaKey && 'Win',
        event.key === ' ' ? 'Space' : event.key.length === 1 ? event.key.toUpperCase() : event.key].filter(Boolean).join('+');
      report('快捷键 ' + field.value);
    }
    if (field.matches('[data-app-folder-edit]') && ['Enter','Escape'].includes(event.key)) {
      if (event.key === 'Enter' && field.value.trim()) {
        setLabel(select('[data-app-action="folder-toggle"]'),
          field.value.trim() + (select('[data-app-folder-content]').hidden ? ' ▸' : ' ▾'));
      }
      field.hidden = true;
      select('[data-app-action="folder-name"]').focus();
    }
    if (event.key === 'Enter' && field.matches('textarea[data-app-room-input]') && event.ctrlKey) {
      event.preventDefault();
      select('[data-app-action="room-add"]').click();
    }
    if (item.id === 'danmaku-panel' && event.key === 'Enter' && field.matches('[data-app-value]') && field.value.trim()) {
      const panel = select('[data-app-comments]');
      const line = document.createElement('div');
      line.textContent = '示例：' + field.value.trim();
      panel.append(line);
      field.value = '';
      if (select('[data-app-action=follow-comments]').getAttribute('aria-pressed') !== 'false') panel.scrollTop = panel.scrollHeight;
      report('已添加到网页预览');
    }
    if (event.key === 'Enter' && presetForm?.contains(field)) select('[data-app-action=save]').click();
    if (event.key === 'Escape' && presetForm?.contains(field)) select('[data-app-action=cancel]').click();
    if (event.key === 'Enter' && item.id === 'blocked-users' && field.matches('[data-app-value]')) select('[data-app-action=block-add]').click();
    if (event.altKey && ['ArrowUp','ArrowDown'].includes(event.key) && field.matches('.lab-app-order-row')) {
      event.preventDefault();
      const down = event.key === 'ArrowDown';
      move(field, down ? field.nextElementSibling : field.previousElementSibling, down);
      field.focus();
    }
  });

  demo.addEventListener('dragstart', event => {
    dragged = event.target.closest('.lab-app-order-row,[data-app-action=pip-primary]');
    if (dragged) event.dataTransfer.setData('text/plain', dragged.textContent.trim());
  });
  demo.addEventListener('dragover', event => {
    if (dragged && event.target.closest('.lab-app-order-row,[data-app-action=pip-primary]')) event.preventDefault();
  });
  demo.addEventListener('drop', event => {
    const target = event.target.closest('.lab-app-order-row,[data-app-action=pip-primary]');
    if (!dragged || !target) return;
    event.preventDefault();
    if (target.matches('[data-app-action=pip-primary]')) {
      if (dragged === target) return;
      const order = [...target.parentElement.children];
      [order[order.indexOf(dragged)], order[order.indexOf(target)]] = [target, dragged];
      target.parentElement.append(...order);
      report('已交换画面位置');
      return;
    }
    move(dragged, target, event.clientY > target.getBoundingClientRect().y + target.offsetHeight / 2);
  });
  demo.addEventListener('dragend', () => { dragged = null; });

  demo.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const label = text(button);
    const dialog = select('dialog');
    const popup = select('[popover]');
    if (button.hasAttribute('data-app-choice')) {
      const selection = button.dataset.appChoice;
      button.closest('.lab-app-choice').querySelectorAll('button').forEach(option => option.setAttribute('aria-pressed', option === button));
      if (selection === 'remove-scope') all('[data-app-pane]').forEach(pane => { pane.checked = !pane.disabled &&
        (label === '选择全部直播' || (label === '选择未开播' && pane.hasAttribute('data-app-offline'))); });
      if (selection === 'remove-scope') updateSelection();
      if (selection === 'layout') select('[data-app-layout-current]').textContent = '当前：' + label;
      if (selection === '布局分类') {
        select('[data-app-layout-group]').textContent = label === '普通布局' ? '均分' : label;
        all('[data-app-choice=layout]').forEach((card,index) => {
          const [name,spec] = labLayoutOptions[label][index];
          card.firstElementChild.outerHTML = labLayoutSwatch(spec);
          card.lastElementChild.textContent = name;
          card.setAttribute('aria-label',name);
          card.setAttribute('aria-pressed',select('[data-app-layout-current]').textContent === '当前：' + name);
        });
      }
      if (selection === 'pip-columns') select('.lab-app-panes').style.setProperty('--pane-columns', label === '一列' ? 1 : 2);
      if (selection === 'skin') {
        if (label === '导入背景') select('[data-app-skin]').click();
        else {
          const preview = select('[data-app-skin-preview]');
          preview.textContent = '默认背景';
          preview.hidden = true;
        }
      }
      if (selection === '主题色') {
        const field = select('[data-app-theme-color]');
        field.value = button.dataset.appColor;
        field.dispatchEvent(new Event('input',{bubbles:true}));
      }
      report('已选 ' + label);
      return;
    }
    const action = button.dataset.appAction;
    const input = select('[data-app-value]');
    switch (action) {
      case 'open':
        if (presetForm) { presetForm.hidden = false; input.focus(); }
        else dialog.showModal();
        break;
      case 'cancel':
        if (presetForm) { presetForm.hidden = true; select('[data-app-action=open]').focus(); }
        else dialog.close();
        report('已取消');
        break;
      case 'delete': dialog.close(); report('已确认删除示例插件'); break;
      case 'save': {
        const name = input.value.trim();
        if (!name) { report('请输入名称'); input.focus(); break; }
        const folder = select('.lab-app-folder-preview');
        if (folder) {
          folder.lastElementChild.textContent = name;
          folder.firstElementChild.innerHTML = labIcon(folderGlyph);
          folder.firstElementChild.style.color = folderColor.value;
        }
        if (presetForm) {
          presetForm.hidden = true;
          select('[data-app-preset-list]').textContent = name;
          select('[data-app-action=open]').focus();
        } else dialog.close();
        report('已保存 ' + name);
        break;
      }
      case 'room-add': {
        const lines = updateRooms();
        const valid = lines.every(value => /^\d+$/.test(value) || /^https?:\/\/[^\s]+$/i.test(value));
        const error = select('[data-app-room-error]');
        error.hidden = valid;
        error.textContent = '请输入房间号或链接';
        report(valid ? `已准备添加 ${lines.length} 个直播间` : '请输入房间号或链接');
        break;
      }
      case 'room-editor-open':
      case 'room-editor-close': {
        const open = action === 'room-editor-open';
        select('[data-app-room-editor]').hidden = !open;
        select('[data-app-room-reopen]').hidden = open;
        if (open) select('[data-app-room-input]').focus();
        break;
      }
      case 'import': report('已选 ' + all('[data-app-import]:checked').length + ' 项'); break;
      case 'folder-toggle': {
        const list = select('[data-app-folder-content]');
        list.hidden = !list.hidden;
        button.setAttribute('aria-expanded', !list.hidden);
        report(list.hidden ? '文件夹已收起' : '文件夹已展开');
        break;
      }
      case 'folder-name': {
        const field = select('[data-app-folder-edit]');
        field.hidden = false;
        field.value = select('[data-app-action="folder-toggle"]').textContent.trim().replace(/ [▾▸]$/, '');
        field.focus();
        field.select();
        break;
      }
      case 'folder-icon':
        folderGlyph = button.dataset.appFolderGlyph;
        all('[data-app-folder-glyph]').forEach(icon => icon.setAttribute('aria-pressed', icon === button));
        select('.lab-qt-icon-current > span').innerHTML = labIcon(folderGlyph);
        break;
      case 'folder-reset':
        select('[data-app-folder-glyph=folder]').click();
        folderColor.value = '#00a1d6';
        folderColor.dispatchEvent(new Event('input',{bubbles:true}));
        break;
      case 'folder-color':
        folderColor.value = button.dataset.appColor;
        folderColor.dispatchEvent(new Event('input',{bubbles:true}));
        break;
      case 'popup-close': popup.hidePopover(); break;
      case 'layout-reset': report('已恢复当前布局默认比例'); break;
      case 'theme-size-down':
      case 'theme-size-up': {
        const size = select('[data-app-theme-size]');
        size.value = Math.max(Number(size.min), Math.min(Number(size.max), Number(size.value) + (action === 'theme-size-up' ? 1 : -1)));
        size.dispatchEvent(new Event('input',{bubbles:true}));
        break;
      }
      case 'remove': {
        const selected = all('[data-app-pane]:checked:not(:disabled)');
        if (selected.length) lastRemoved = selected;
        selected.forEach(pane => { pane.disabled = true; pane.checked = false; pane.closest('label').hidden = true; });
        updateSelection();
        report(selected.length ? '已移除 ' + selected.length + ' 路' : '请选择画面');
        break;
      }
      case 'undo':
        lastRemoved.forEach(pane => { pane.disabled = false; pane.closest('label').hidden = false; });
        report(lastRemoved.length ? '已撤回移除' : '暂无可撤回记录');
        lastRemoved = [];
        updateSelection();
        break;
      case 'pip-primary':
        all('[data-app-action="pip-primary"]').forEach(pane => pane.setAttribute('aria-pressed', pane === button));
        report('主画面 · ' + label);
        break;
      case 'mute': {
        const silent = toggle(button);
        paintIcon(button, silent ? 'qt-mute' : 'qt-volume');
        report(silent ? '已静音' : '声音已开启');
        break;
      }
      case 'toggle': report((toggle(button) ? '已开启 ' : '已关闭 ') + label); break;
      case 'caption-mode':
      case 'caption-smaller':
      case 'caption-larger':
      case 'caption-reset': changeCaption(action); break;
      case 'bottom': {
        const list = select('[data-app-comments]');
        list.scrollTop = list.scrollHeight;
        report('已回到底部');
        break;
      }
      case 'follow-comments': {
        const follow = button.getAttribute('aria-pressed') !== 'false';
        button.setAttribute('aria-pressed', !follow);
        const list = select('[data-app-comments]');
        if (!follow) list.scrollTop = list.scrollHeight;
        report(follow ? '已暂停跟随' : '已继续跟随');
        break;
      }
      case 'sc-toggle':
        select('[data-app-sc] p').hidden = toggle(button);
        report(select('[data-app-sc] p').hidden ? '醒目留言已收起' : '醒目留言已展开');
        break;
      case 'sc-close':
      case 'sc-restore': select('[data-app-sc]').hidden = action === 'sc-close'; report(action === 'sc-close' ? '已关闭' : '已恢复'); break;
      case 'settings-close':
      case 'settings-restore': {
        const closed = action === 'settings-close';
        select('[data-app-title]').hidden = closed;
        select('[data-app-title-closed]').hidden = !closed;
        report(closed ? '设置窗口已关闭' : '设置示例已恢复');
        break;
      }
      case 'shortcut-clear':
      case 'shortcut-reset':
        select('[data-app-shortcut]').value = action === 'shortcut-clear' ? '' : 'M';
        report(action === 'shortcut-clear' ? '快捷键已清除' : '已恢复默认快捷键');
        break;
      case 'close-choice':
        dialog.close();
        report('已选 ' + label + (select('[data-app-remember]').checked ? ' · 记住选择' : ''));
        break;
      case 'cache-segment': {
        const checks = all('[data-app-cache]');
        if (event.detail) {
          const rect = button.getBoundingClientRect();
          const x = event.clientX - rect.x - rect.width / 2;
          const y = rect.y + rect.height / 2 - event.clientY;
          const radius = Math.hypot(x,y) / (rect.width / 2);
          if (radius <= .57 || radius >= 1) break;
          const angle = (Math.atan2(x,y) * 180 / Math.PI + 360) % 360;
          checks[angle < 270 ? 0 : 1].click();
        } else {
          const checked = !checks.every(entry => entry.checked);
          checks.forEach(entry => { entry.checked = checked; });
          cache.dataset.selected = checked ? '11' : '00';
          report(checked ? '已选择缓存分类' : '已取消选择');
        }
        break;
      }
      case 'cache-clear': {
        const checked = all('[data-app-cache]:checked');
        checked.forEach(entry => { entry.checked = false; });
        cache.dataset.selected = '00';
        report(checked.length ? '已完成示例清理 · ' + checked.length + ' 项' : '请选择缓存分类');
        break;
      }
      case 'block-add': {
        const uid = input.value.trim();
        if (/^\d+$/.test(uid)) { addListValue(uid); input.value = ''; }
        else report('请输入数字 UID');
        break;
      }
      case 'block-remove':
      case 'list-remove': clearSelected(); break;
      case 'up':
      case 'down': {
        const row = button.closest('.lab-app-order-row');
        move(row, action === 'up' ? row.previousElementSibling : row.nextElementSibling, action === 'down');
        break;
      }
      case 'read': select('[data-app-notice]').dataset.read = 'true'; clearUnread(); report('已标记为已读'); break;
      case 'clear-notices': select('[data-app-notice]').hidden = true; clearUnread(); popup.hidePopover(); report('暂无通知'); break;
      case 'update-close':
      case 'update-restore': {
        const closed = action === 'update-close';
        select('[data-app-update]').hidden = closed;
        select('[data-app-update-closed]').hidden = !closed;
        report(closed ? '提醒已关闭' : '提醒已恢复');
        break;
      }
      case 'restore': report('已触发恢复主窗口'); break;
      case 'path': input.value = 'D:/示例/直播录制'; report('已选示例目录'); break;
      case 'diagnostic-add': addListValue('示例附件.png'); break;
      case 'diagnostic-export': report('示例诊断包已准备'); break;
      case 'source':
        all('[data-app-action=source]').forEach(room => room.setAttribute('aria-pressed', room === button));
        popup.hidePopover();
        popupTrigger.title = '弹幕来源：' + label;
        popupTrigger.setAttribute('aria-label', popupTrigger.title);
        popupTrigger.querySelector('.lab-label').textContent = label[0];
        paintIcon(popupTrigger,'');
        report('弹幕来源：' + label);
        break;
      case 'comment-copy':
        popup.hidePopover();
        if (navigator.clipboard) {
          navigator.clipboard.writeText('晚上好').then(() => report('已复制示例弹幕'), () => report('示例弹幕：晚上好'));
        } else report('示例弹幕：晚上好');
        break;
      case 'chat-float':
      case 'chat-return': {
        const floating = action === 'chat-float';
        select('[data-app-float-panel]').classList.toggle('lab-app-floating', floating);
        select('[data-app-float-slot]').hidden = !floating;
        select('[data-app-action=chat-float]').hidden = floating;
        report(floating ? '弹幕已转为浮窗' : '弹幕已收回');
        break;
      }
      case 'skin-part':
        skinPart = button;
        all('[data-app-part]').forEach(part => part.setAttribute('aria-pressed', part === button));
        report('已选 ' + label);
        break;
      case 'profile-room': {
        const wasSelected = button.getAttribute('aria-pressed') === 'true';
        all('[data-app-action=profile-room]').forEach(room => room.setAttribute('aria-pressed', !wasSelected && room === button));
        profileRoom = wasSelected ? null : label;
        select('[data-app-profile]').textContent = wasSelected ? '编辑整组 · 2 位主播' : '编辑 ' + label;
        showProfile(true);
        break;
      }
      case 'profile-expand':
        showProfile(profileForm.hidden);
        break;
      case 'profile-remove':
        for (const room of profileRoom ? [profileRoom] : Object.keys(profileValues)) {
          profileValues[room] = ['继承','继承','-1'];
        }
        showProfile(!profileForm.hidden);
        report('已移除示例主播设置');
        break;
      case 'profile-refresh':
        report('已刷新示例画质');
        break;
      case 'notice-confirm': dialog.close(); report('已确认示例须知'); break;
      case 'report': if (popup?.matches(':popover-open')) popup.hidePopover(); report('已触发 ' + label); break;
      case 'room': report('已选择 ' + button.dataset.appFind.split(' ')[0]); break;
    }
  });
  if (item.id === 'volume-popup') {
    const popup = select('[popover]');
    popupTrigger.setAttribute('popovertargetaction', 'show');
    popupTrigger.addEventListener('pointerenter', event => {
      if (event.pointerType === 'mouse' && !popupTrigger.matches(':disabled') && !popup.matches(':popover-open')) popup.showPopover({source:popupTrigger});
    });
  }
  if (item.id === 'comment-actions') {
    popupTrigger.addEventListener('contextmenu', event => {
      if (popupTrigger.matches(':disabled')) return;
      event.preventDefault();
      const popup = select('[popover]');
      if (!popup.matches(':popover-open')) popup.showPopover({source:popupTrigger});
    });
  }
  if (item.id === 'wall-remove') {
    demo.addEventListener('change', event => { if (event.target.matches('[data-app-pane]')) updateSelection(); });
    updateSelection();
  }
  if (item.id === 'notices') {
    select('[popover]').addEventListener('toggle', event => { if (event.newState === 'open') clearUnread(); });
  }
}
