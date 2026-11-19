// Matches the Windows Qt capture rows in ui-control-library-qt-application.png.
const labApplicationControls = [
  ['room-search', '关注搜索框', '关注栏 › 搜索主播／房间号', 217, 'room_add_followed.py', '输入中文、拼音或房间号，查看结果与空态。'],
  ['room-add', '批量添加直播间', '关注栏 › 添加与导入', 232, 'room_add_panel.py', '每行一个房间号或直播间链接。选择文件夹后试用数量与错误反馈。'],
  ['room-picker', '关注直播间选择器', '添加直播间 › 从关注列表选择', 234, 'room_add_followed.py', '搜索关注项、筛选直播中并选择一项。'],
  ['follow-import', '导入关注列表', '添加与导入 › 导入关注', 232, 'follow_import_ui.py', '核对复选、已关注禁用和导入数量。'],
  ['follow-card', '关注卡片多选', '关注列表 › 多选管理', 212, 'sidebar_item.py', '选择卡片，查看主播标题和开播状态。'],
  ['folder-head', '关注文件夹标题', '关注列表 › 文件夹', 204, 'sidebar_folders.py', '展开或收起文件夹，也可进入行内重命名。'],
  ['folder-edit', '文件夹名称与图标', '关注列表 › 新建／编辑文件夹', 244, 'folder_icons.py', '填写名称、选择颜色，确认后立即显示。'],
  ['function-hub', '功能中心', '侧栏 › 功能中心', 233, 'workspace_controls.py', '搜索功能、切换固定状态，或打开插件管理入口。'],
  ['account-menu', '账号行与账号菜单', '关注栏底部 › 账号', 195, 'account_widgets.py', '打开账号操作菜单。示例使用虚构账号。'],
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
  ['streamer-profile', '主播独立设置卡', '主播设置 › 主播卡片', 236, 'settings_streamer_profiles.py', '在整组和单个主播间切换，修改画质和音量。'],
  ['startup-notice', '首次启动须知', '首次启动 › 用户须知', 200, 'user_notice.py', '滚动阅读试样，确认后查看反馈。'],
  ['settings-material', '视觉效果与设置布局', '外观 › 视觉效果', 248, 'settings_material_editor.py', '切换毛玻璃、阴影、分段指示器和设置卡片布局，试调底色不透明度。'],
].map(([id, title, location, width, file, usage], row) => ({
  id, title, location, width, usage, height: id === 'pip-tools' ? 24 : 32, radius: id === 'pip-tools' ? 12 : 8, source: 'ddm/' + file,
  row, sheet: 'application', area: 'settings',
  group: row < 9 || (row >= 36 && row < 38) ? '添加与关注'
    : (row < 22 || (row >= 38 && row < 42)) ? '画面墙与播放' : '系统与设置',
}));

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
  const line = (label, control) => `<label class="lab-app-line"><span>${label}</span>${control}</label>`;
  const searchRows = `
    <button class="lab-app-row lab-control" data-app-action="room" data-app-find="小岚 xiaolan xl 10001" data-app-live><i></i>小岚<span>直播中</span></button>
    <button class="lab-app-row lab-control" data-app-action="room" data-app-find="阿海 ahai ah 10002"><i></i>阿海<span>未开播</span></button>
    <small data-app-empty hidden>没有匹配的关注</small>`;
  const searchBox = label => field(label, 'search', `placeholder="${label}" data-app-search data-primary`);
  const panes = (count, selectAction = '') => `<div class="lab-app-panes" style="--pane-columns:${count === 4 ? 2 : count}">
    ${Array.from({length:count}, (_, i) => selectAction
      ? `<button class="lab-control" type="button" data-app-action="${selectAction}" aria-pressed="${i === 0}">${['小岚','阿海','星河','画面 4'][i]}</button>`
      : '<span></span>').join('')}</div>`;
  let html;
  switch (item.id) {
    case 'room-search': html = searchBox('搜索主播 / 房间号') + searchRows; break;
    case 'room-add':
      html = `<textarea class="lab-app-field" rows="2" aria-label="房间号或链接" placeholder="房间号或链接，每行一个" data-app-room-input data-primary>10001</textarea>
        <div class="lab-app-choice">${select(['默认分组','收藏'], '添加到文件夹')}${b('添加 1 个','room-add')}</div>`; break;
    case 'room-picker':
      html = `<div class="lab-app-choice">${searchBox('搜索关注主播 / 房间号')}${check('直播中', false, 'data-app-filter-live')}</div>${searchRows}`; break;
    case 'follow-import':
      html = `${choice(['哔哩哔哩','其他平台'])}<div class="lab-app-stack">${check('小岚',true,'data-app-import')}${check('阿海',false,'data-app-import')}
        ${check('星河 · 已关注', true, 'disabled')}${b('导入所选','import',true)}</div>`; break;
    case 'follow-card':
      html = `<label class="lab-app-follow" data-primary><input type="checkbox" checked aria-label="选中小岚"><i>小</i><span><strong>小岚</strong><small>午后直播</small></span><small>直播中</small></label>`; break;
    case 'folder-head':
      html = `${b('默认分组 ▾','folder-toggle',true)}<div data-app-folder-content>${searchRows}</div>
        ${b('重命名','folder-name')}${field('文件夹名称','text','data-app-folder-edit hidden')}`; break;
    case 'folder-edit':
      html = dialog('编辑文件夹','编辑文件夹', `${line('名称',field('文件夹名称','text','value="默认分组" data-app-value'))}
        ${line('图标颜色',field('图标颜色','color','value="#00a1d6" data-app-folder-color'))}${b('取消','cancel')}${b('确定','save')}`)
        + '<div class="lab-app-folder-preview"><span aria-hidden="true">▰</span> <span>默认分组</span></div>'; break;
    case 'function-hub':
      html = popupButton('功能中心', `${searchBox('搜索功能、插件')}
        <div class="lab-app-stack" data-app-find="插件商店 chajianshangdian cjsd">${b('插件商店 / 管理插件','report')}${check('固定常用',false)}</div>
        <div class="lab-app-stack" data-app-find="插件功能 chajiangongneng cjgn">${b('插件功能','report')}</div><small data-app-empty hidden>暂无匹配功能</small>`, 'box'); break;
    case 'account-menu':
      html = popupButton('示例账号 ⋯', `<p class="lab-app-note">哔哩哔哩 · 示例账号</p>
        ${b('管理账号','report')}${b('切换账号','report')}${b('退出登录','report')}`); break;
    case 'layout-picker':
      html = `<div class="lab-app-choice lab-layouts">${[1,2,4].map((count,index) =>
        `<button class="lab-control lab-layout-card" data-app-choice="layout" aria-pressed="${index===0}" ${index ? '' : 'data-primary'}>${panes(count)}${count} 画面</button>`).join('')}</div>`; break;
    case 'room-preset':
      html = dialog('保存当前组合…','保存当前组合', `${line('组合名称',field('组合名称','text','placeholder="输入当前组合的名称" data-app-value'))}
        ${b('取消','cancel')}${b('保存','save')}`); break;
    case 'wall-remove':
      html = `${check('小岚 · 直播中',false,'data-app-pane')}${check('阿海 · 未开播',false,'data-app-pane data-app-offline')}
        ${choice(['选择未开播','选择全部直播','取消选择'],'remove-scope', -1)}
        <div class="lab-app-choice">${b('撤回上次移除','undo')}${b('移除所选','remove',true)}</div>`; break;
    case 'wall-quick':
      html = `${line('整体音量',labRange('整体音量',0,100,48,'',true))}
        ${line('画质',select(['选择画质','原画','超清 720P','流畅'], '画质'))}${toggle('画面弹幕',true)}${toggle('弹幕浮窗',false)}`; break;
    case 'pip-composer':
      html = choice(['一列','两列'],'pip-columns',1) + panes(2,'pip-primary'); break;
    case 'pip-tools':
      html = `<div class="lab-app-choice">${b('选择画面组合','report',true,'display')}${b('调整画面位置','toggle',false,'panel')}
        ${b('置顶画中画','toggle',false,'pin')}${b('返回监控室','report',false,'minimize')}${b('关闭画中画','report',false,'close')}</div>`; break;
    case 'pip-audio':
      html = `<div class="lab-app-choice">${b('小岚静音','mute',true,'qt-volume')}${labRange('小岚音量',0,100,40,'%')}</div>`; break;
    case 'volume-popup':
      html = popupButton('音量', `<div class="lab-app-vertical">${labRange('音量',0,100,40)}</div>`, 'qt-volume'); break;
    case 'stream-state':
      html = `<div class="lab-stream-status">${labIcon('display')}<span data-app-stream>连接中…</span></div>${select(['连接中…','缓冲中…','直播中','已暂停','已下播'],'播放状态')}`; break;
    case 'stream-info':
      html = dialog('直播流信息','直播流信息', `<p>示例直播间 · 直播源参数</p>
        <dl class="lab-app-stats"><dt>视频编码</dt><dd>H.264</dd><dt>分辨率</dt><dd>1920×1080</dd><dt>帧率</dt><dd>60 fps</dd></dl>${b('关闭','cancel')}`); break;
    case 'caption-tools':
      html = `<p data-app-caption>字幕预览</p><div class="lab-app-choice">
        ${b('字幕显示内容','caption-mode',true,'display')}${b('减小字号','caption-smaller',false,'minus')}
        ${b('增大字号','caption-larger',false,'plus')}${b('恢复位置与大小','caption-reset',false,'refresh')}${b('锁定字幕位置','toggle',false,'pin')}</div>`; break;
    case 'danmaku-panel':
      html = `<div class="lab-app-choice">${b('回到底部','bottom',true)}${check('跟随',true,'data-app-follow')}${labRange('弹幕字号',8,32,13,' px')}</div>
        <div class="lab-app-comments" data-app-comments tabindex="0">小岚：晚上好<br>阿海：欢迎来到直播间</div>
        ${field('输入示例弹幕','text','placeholder="输入示例弹幕" data-app-value')}`; break;
    case 'super-chat':
      html = `<article class="lab-app-sc" data-app-sc><div class="lab-app-sc-head"><span class="lab-app-avatar" aria-hidden="true">小</span>
        <span>小岚<strong>¥30</strong></span><small>剩 0:30</small>${b('展开／收起','sc-toggle',true,'down')}${b('关闭','sc-close',false,'close')}</div>
        <p>感谢直播，今天也很开心！</p></article>${b('恢复示例','sc-restore')}`; break;
    case 'shortcut-edit':
      html = `<div class="lab-app-shortcut">${line('静音',field('静音快捷键','text','value="M" readonly data-app-shortcut data-primary'))}
        ${toggle('启用',true,'data-app-shortcut-enable')}${b('恢复','shortcut-reset')}</div>`; break;
    case 'settings-caption':
      html = `<div class="lab-app-choice" data-app-title><strong>设置 › 常规</strong>${b('关闭设置','settings-close',true,'close')}</div>
        ${b('恢复示例','settings-restore')}`; break;
    case 'close-choice':
      html = dialog('关闭窗口','关闭窗口', `<p>关闭窗口后，你希望程序如何运行？</p>${check('记住我的选择',false,'data-app-remember')}
        <div class="lab-app-choice">${b('隐藏到托盘','close-choice')}${b('退出程序','close-choice')}</div>`); break;
    case 'cache-pie':
      html = `<div class="lab-app-cache">${b('图片缓存 100 MB','cache-segment',true)}<div>
        ${check('头像 75 MB',false,'data-app-cache')}${check('封面 25 MB',false,'data-app-cache')}
        ${b('清理所选','cache-clear')}` + '</div></div>'; break;
    case 'skin-library':
      html = `${choice(['默认背景','导入预览'],'skin')}${field('导入背景','file','accept="image/*" data-app-skin hidden')}
        <div class="lab-app-skin-preview" data-app-skin-preview>默认背景</div>`; break;
    case 'blocked-users':
      html = `<div class="lab-app-choice">${field('用户 UID','text','placeholder="输入数字 UID" inputmode="numeric" data-app-value data-primary')}
        ${b('添加','block-add')}</div><select size="2" class="lab-control lab-app-field" aria-label="已屏蔽用户" data-app-list><option>10001</option></select>${b('移除所选','block-remove')}`; break;
    case 'audio-response':
      html = `<svg viewBox="0 0 230 58" class="lab-app-response" aria-label="时间响应预览"><path d="M3 8H227M3 28H227M3 50H227" class="lab-curve-grid"></path><path class="lab-curve-line" d="M4 8H52L71 47H104Q150 47 224 8"></path></svg>
        ${line('恢复时间',field('恢复时间（秒）','number','min="1" max="30" step=".1" value="8" data-app-response data-primary'))}`; break;
    case 'menu-order':
      html = `<div class="lab-app-order" data-app-order>${['音量','画质','当前窗口编解码设置'].map((label,index) =>
        `<div draggable="true" class="lab-app-order-row">${toggle(label,true)}${b('上移','up',index===0,'down')}${b('下移','down',false,'down')}</div>`).join('')}</div>`; break;
    case 'notices':
      html = popupButton('通知 · 1 条未读', `<p>通知 · 本次启动</p><div data-app-notice><p>示例直播间开播了</p>${b('标记已读','read')}</div>${b('清空通知','clear-notices')}`, 'bell'); break;
    case 'update-notice':
      html = `<article class="lab-app-note" data-app-update><strong>版本更新</strong><p>发现新版本</p>
        <div class="lab-app-choice">${b('查看更新','report',true)}${b('关闭','update-close',false,'close')}</div></article>${b('恢复提醒','update-restore')}`; break;
    case 'tray-layout':
      html = `<button class="lab-control lab-app-tray" data-app-action="restore" data-primary>${panes(2)}点击恢复主窗口</button>`; break;
    case 'record-path':
      html = `<div class="lab-app-choice lab-app-path">${field('保存目录','text','value="C:/示例/录制" data-app-value data-primary')}
        ${b('浏览…','path')}</div>`; break;
    case 'diagnostic-form':
      html = `<select size="2" class="lab-control lab-app-field" aria-label="附加图片" data-app-list data-primary><option>示例截图.png</option></select>
        <div class="lab-app-choice">${b('添加示例图片','diagnostic-add')}${b('移除所选','list-remove')}</div>${b('导出诊断包','diagnostic-export')}`; break;
    case 'smart-folder':
      html = dialog('编辑智能文件夹','编辑智能文件夹', `${line('名称',field('智能文件夹名称','text','value="直播中" data-app-value'))}
        <div class="lab-app-choice">${check('默认分组',true,'data-app-smart')}${check('收藏',false,'data-app-smart')}</div>
        ${line('显示方式',select(['匹配时移入显示','在两处显示'],'显示方式'))}
        ${line('开播状态',select(['开播','未开播','全部状态'],'开播状态'))}
        ${line('卡片排序',select(['自定义','常看优先'],'卡片排序'))}
        <div class="lab-app-choice">${check('哔哩哔哩')}${check('虎牙')}${b('取消','cancel')}${b('保存','save')}</div>`); break;
    case 'account-platform':
      html = choice(['B站','虎牙','斗鱼'],'账号平台'); break;
    case 'danmaku-source':
      html = popupButton('选择弹幕来源', `<div class="lab-app-choice lab-app-source">${avatar('小岚','source')}${avatar('阿海','source')}</div>`, 'display'); break;
    case 'comment-actions':
      html = popupButton('小岚：晚上好', `<div class="lab-app-choice">${b('复制','comment-copy')}${b('+1','report')}
        ${b('屏蔽弹幕','report')}${b('屏蔽用户','report')}</div>`); break;
    case 'danmaku-float':
      html = `<div class="lab-app-note" data-app-float-panel>弹幕 · 示例直播间<p>小岚：晚上好</p></div>
        ${b('弹幕浮窗','chat-float',true)}<div data-app-float-slot hidden>${b('收回弹幕栏','chat-return')}</div>`; break;
    case 'caption-placement':
      html = `<div class="lab-app-caption-stage"><button class="lab-control" type="button" data-primary
        data-app-caption-move aria-label="字幕位置，使用方向键移动">今天和大家一起享受游戏。</button></div>
        ${labRange('字幕大小',10,24,14,' px')}${b('恢复位置与大小','caption-place-reset')}`; break;
    case 'theme-editor':
      html = `<div class="lab-app-choice lab-swatches" role="group" aria-label="主题色">${labPresets.map(([color, label],index) => `
        <button type="button" class="lab-control ${index ? 'lab-swatch-dot' : ''}" aria-label="${label}" title="${label}"
          aria-pressed="${index === 0}" data-app-choice="主题色" data-app-color="${color}"
          ${index ? `style="--swatch:${color}"` : ''}>${index ? '' : label}</button>`).join('')}</div>
        ${line('自定义色值',field('自定义色值','text','placeholder="#RRGGBB" maxlength="7" data-app-theme-color data-primary'))}
        ${line('界面字体',select(['系统默认','微软雅黑','等宽字体'],'界面字体'))}
        ${line('界面字号',field('界面字号','number','min="11" max="20" value="13" data-app-theme-size'))}
        <div class="lab-app-note" data-app-theme-sample>关注列表 · 示例主播</div>`; break;
    case 'skin-parts':
      html = `${select(['主界面','设置页面','菜单与提示'],'预览场景')}
        <div class="lab-app-choice" data-app-skin-areas>${b('关注栏','skin-part',true)}${b('控制区','skin-part')}${b('播放区','skin-part')}</div>
        ${line('分区底色',field('分区底色','color','value="#007ba8" data-app-part-color'))}`; break;
    case 'notice-blur':
      html = `<div class="lab-app-blur" data-app-blur data-banner="true"><span></span><p>开播提醒<br>示例主播开播了</p></div>
        ${toggle('使用直播封面',true,'data-app-banner')}${labRange('模糊程度',0,32,16)}`; break;
    case 'streamer-profile':
      html = `<div class="lab-app-choice lab-app-source">${avatar('小岚','profile-room',true)}${avatar('阿海','profile-room')}${b('展开设置','profile-expand')}</div>
        <div class="lab-app-note" data-app-profile>编辑整组 · 2 位主播</div>
        <div data-app-profile-form hidden>${line('默认播放画质',select(['继承','原画','超清 720P'],'默认播放画质'))}
        ${line('录制画质',select(['继承','原画','超清 720P'],'录制画质'))}${labRange('默认音量',0,100,40,'%')}</div>`; break;
    case 'startup-notice':
      html = dialog('阅读用户须知','用户须知', `<div class="lab-app-reading" tabindex="0">
        <p>DD 监控室 CE 是免费开源软件。请从项目官方渠道获取软件与更新。</p>
        <p>本软件独立于第三方直播平台。使用登录和插件功能前，请了解各自来源和权限。</p>
        <p>请遵守平台规则，尊重主播及其他权利人的权益。</p></div>${b('我已阅读并确认','notice-confirm')}`); break;
    case 'settings-material':
      html = `<div class="lab-app-material" data-app-material data-glass="false" data-shadows="true" data-columns="自动">
        <span>常规</span><span>外观</span></div>
        ${toggle('启用毛玻璃效果',false,'data-app-glass')}
        <div data-app-opacity hidden>${line('底色不透明度',labRange('底色不透明度',0,100,70,'%'))}</div>
        ${toggle('滑动分段指示器',true,'data-app-segment-motion')}${toggle('禁用卡片与控件阴影',false,'data-app-no-shadows')}
        ${line('设置卡片布局',select(['自动','单列','双列'],'设置卡片布局'))}
        <div class="lab-app-choice lab-app-material-segment" data-app-material-segment>${choice(['常规','外观'],'设置分类')}</div>`; break;
    case 'plugin-remove':
      html = dialog('删除插件','删除这个插件？', `<p>将删除插件“示例插件”及其文件。</p>
        <div class="lab-app-choice">${b('取消','cancel')}${b('删除','delete')}</div>`);
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
  const caption = select('[data-app-caption-move]');
  const skinAreas = select('[data-app-skin-areas]');
  const material = select('[data-app-material]');
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
    const terms = (select('[data-app-search]')?.value || '').toLowerCase().trim().split(/\s+/);
    const live = select('[data-app-filter-live]')?.checked;
    const rows = all('[data-app-find]');
    rows.forEach(row => { row.hidden = !terms.every(term => row.dataset.appFind.includes(term)) || Boolean(live && !row.hasAttribute('data-app-live')); });
    const empty = select('[data-app-empty]');
    if (empty) empty.hidden = rows.some(row => !row.hidden);
  }

  function updateRooms() {
    const unique = [...new Set(select('[data-app-room-input]').value.split(/\n/).map(line => line.trim()).filter(Boolean))];
    const button = select('[data-app-action="room-add"]');
    setLabel(button, unique.length ? `添加 ${unique.length} 个` : '添加');
    button.disabled = !unique.length;
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
        const areas = [['关注栏','控制区','播放区'],['分类','内容区','按钮'],['菜单','提示','对话框']];
        [...skinAreas.children].forEach((button, index) => {
          setLabel(button, areas[target.selectedIndex][index]);
          button.removeAttribute('aria-pressed');
          button.style.removeProperty('--lab-surface');
        });
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
      if (target.matches('[data-app-segment-motion]')) select('[data-app-material-segment]').dataset.motion = target.checked;
      report((target.checked ? '已选 ' : '已取消 ') + (target.getAttribute('aria-label') || target.closest('label')?.textContent.trim() || ''));
    }
    if (target.matches('[data-app-response]') && target.validity.valid && target.value) {
      const end = 102 + Number(target.value) * 4;
      select('.lab-curve-line').setAttribute('d', `M4 8H52L71 47H104Q${end} 47 ${Math.min(224,end+35)} 8H224`);
      report('恢复时间 ' + target.value + ' 秒');
    }
    if (target.matches('[data-app-folder-color]')) {
      target.closest('dialog')?.style.setProperty('--lab-accent', target.value);
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
    const image = new Image();
    const url = URL.createObjectURL(target.files[0]);
    image.onload = image.onerror = () => URL.revokeObjectURL(url);
    image.src = url;
    image.alt = '导入的本地背景预览';
    select('[data-app-skin-preview]').replaceChildren(image);
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
      if (select('[data-app-follow]').checked) panel.scrollTop = panel.scrollHeight;
      report('已添加到网页预览');
    }
  });

  demo.addEventListener('dragstart', event => {
    dragged = event.target.closest('.lab-app-order-row');
    if (dragged) event.dataTransfer.setData('text/plain', dragged.textContent.trim());
  });
  demo.addEventListener('dragover', event => {
    if (dragged && event.target.closest('.lab-app-order-row')) event.preventDefault();
  });
  demo.addEventListener('drop', event => {
    const target = event.target.closest('.lab-app-order-row');
    if (!dragged || !target) return;
    event.preventDefault();
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
      if (selection === 'pip-columns') select('.lab-app-panes').style.setProperty('--pane-columns', label === '一列' ? 1 : 2);
      if (selection === 'skin') {
        if (label === '导入预览') select('[data-app-skin]').click();
        else select('[data-app-skin-preview]').textContent = '默认背景';
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
      case 'open': dialog.showModal(); break;
      case 'cancel': dialog.close(); report('已取消'); break;
      case 'delete': dialog.close(); report('已确认删除示例插件'); break;
      case 'save': {
        const name = input.value.trim();
        if (!name) { report('请输入名称'); input.focus(); break; }
        const folder = select('.lab-app-folder-preview');
        if (folder) {
          folder.lastElementChild.textContent = name;
          folder.firstElementChild.style.color = select('[data-app-folder-color]').value;
        }
        dialog.close();
        report('已保存 ' + name);
        break;
      }
      case 'room-add': {
        const lines = updateRooms();
        const valid = lines.every(value => /^\d+$/.test(value) || /^https?:\/\/[^\s]+$/i.test(value));
        report(valid ? `已准备添加 ${lines.length} 个直播间` : '请输入房间号或链接');
        break;
      }
      case 'import': report('已选 ' + all('[data-app-import]:checked').length + ' 项'); break;
      case 'folder-toggle': {
        const list = select('[data-app-folder-content]');
        list.hidden = !list.hidden;
        setLabel(button, button.textContent.trim().replace(/ [▾▸]$/, '') + (list.hidden ? ' ▸' : ' ▾'));
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
      case 'remove': {
        const selected = all('[data-app-pane]:checked:not(:disabled)');
        if (selected.length) lastRemoved = selected;
        selected.forEach(pane => { pane.disabled = true; pane.checked = false; pane.closest('label').hidden = true; });
        report(selected.length ? '已移除 ' + selected.length + ' 路' : '请选择画面');
        break;
      }
      case 'undo':
        lastRemoved.forEach(pane => { pane.disabled = false; pane.closest('label').hidden = false; });
        report(lastRemoved.length ? '已撤回移除' : '暂无可撤回记录');
        lastRemoved = [];
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
      case 'sc-toggle':
        select('[data-app-sc] p').hidden = toggle(button);
        report(select('[data-app-sc] p').hidden ? '醒目留言已收起' : '醒目留言已展开');
        break;
      case 'sc-close':
      case 'sc-restore': select('[data-app-sc]').hidden = action === 'sc-close'; report(action === 'sc-close' ? '已关闭' : '已恢复'); break;
      case 'settings-close':
      case 'settings-restore': select('[data-app-title]').hidden = action === 'settings-close'; report(action === 'settings-close' ? '设置窗口已关闭' : '设置示例已恢复'); break;
      case 'shortcut-reset': select('[data-app-shortcut]').value = 'M'; report('已恢复默认快捷键'); break;
      case 'close-choice':
        dialog.close();
        report('已选 ' + label + (select('[data-app-remember]').checked ? ' · 记住选择' : ''));
        break;
      case 'cache-segment': {
        const checks = all('[data-app-cache]');
        if (event.detail) {
          const rect = button.getBoundingClientRect();
          const angle = (Math.atan2(event.clientX - rect.x - rect.width / 2, rect.y + rect.height / 2 - event.clientY) * 180 / Math.PI + 360) % 360;
          checks[angle < 270 ? 0 : 1].click();
        } else {
          const checked = !checks.every(entry => entry.checked);
          checks.forEach(entry => { entry.checked = checked; });
          report(checked ? '已选择缓存分类' : '已取消选择');
        }
        break;
      }
      case 'cache-clear': {
        const checked = all('[data-app-cache]:checked');
        checked.forEach(entry => { entry.checked = false; });
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
      case 'update-restore': select('[data-app-update]').hidden = action === 'update-close'; report(action === 'update-close' ? '提醒已关闭' : '提醒已恢复'); break;
      case 'restore': report('已触发恢复主窗口'); break;
      case 'path': input.value = 'D:/示例/直播录制'; report('已选示例目录'); break;
      case 'diagnostic-add': addListValue('示例附件.png'); break;
      case 'diagnostic-export': report('示例诊断包已准备'); break;
      case 'source':
        all('[data-app-action=source]').forEach(room => room.setAttribute('aria-pressed', room === button));
        popup.hidePopover();
        popupTrigger.title = '弹幕来源：' + label;
        popupTrigger.setAttribute('aria-label', popupTrigger.title);
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
        [...skinAreas.children].forEach(part => part.setAttribute('aria-pressed', part === button));
        report('已选 ' + label);
        break;
      case 'profile-room': {
        const wasSelected = button.getAttribute('aria-pressed') === 'true';
        all('[data-app-action=profile-room]').forEach(room => room.setAttribute('aria-pressed', !wasSelected && room === button));
        select('[data-app-profile]').textContent = wasSelected ? '编辑整组 · 2 位主播' : '编辑 ' + label;
        select('[data-app-profile-form]').hidden = false;
        break;
      }
      case 'profile-expand': {
        const form = select('[data-app-profile-form]');
        form.hidden = !form.hidden;
        setLabel(button, form.hidden ? '展开设置' : '收起设置');
        break;
      }
      case 'notice-confirm': dialog.close(); report('已确认示例须知'); break;
      case 'report': if (popup?.matches(':popover-open')) popup.hidePopover(); report('已触发 ' + label); break;
      case 'room': report('已选择 ' + button.dataset.appFind.split(' ')[0]); break;
    }
  });
  if (item.id === 'volume-popup') {
    const popup = select('[popover]');
    popupTrigger.setAttribute('popovertargetaction', 'show');
    popupTrigger.addEventListener('pointerenter', event => {
      if (event.pointerType === 'mouse' && !popup.matches(':popover-open')) popup.showPopover({source:popupTrigger});
    });
  }
  if (item.id === 'comment-actions') {
    popupTrigger.addEventListener('contextmenu', event => {
      if (popupTrigger.disabled) return;
      event.preventDefault();
      const popup = select('[popover]');
      if (!popup.matches(':popover-open')) popup.showPopover({source:popupTrigger});
    });
  }
}
