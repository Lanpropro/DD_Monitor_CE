const labMatchGroup = '比赛二路插件';
const labExtensions = [{
  id: 'icon-control', title: '通用图标按钮', location: '本体与比赛二路', group: '图标与通用控件',
  width: 320, height: 34, radius: 8, area: 'settings', sheet: 'extension',
  source: 'ddm/sidebar_navigation.py',
  usage: '选取图标后试用同一按钮。详情可调整尺寸、颜色和交互状态，并按分组查看图标来源。',
}, ...[
  ['match-console', '二路播放控制台', '比赛二路 › 播放控制台', 'viewer_ui.py', 'full',
    '顶栏提供自动对齐、对照微调、添加直播间和设置。每路来源按画面、声音、弹幕、偏移和其他操作分列。'],
  ['match-room', '二路来源控制行', '播放控制台 › 每路来源', 'room_widgets.py', 'full',
    '来源头像、主画面选择、声道、弹幕颜色、偏移步进与计时器同处一行。'],
  ['match-compare', '二路画面对照', '播放控制台 › 对照微调', 'comparison.py', 'full',
    '主画面与副路对照并排显示，各自标注来源和对齐状态。右上角提供放大框选区域及收起操作。'],
  ['match-replay', '二路回看时间线', '二路画面 › 回看', 'replay.py', 'full',
    '回看进度条下方是起点、中点和终点刻度。右侧可直接输入时间，旁边的按钮用于返回直播。'],
  ['match-record', '二路录制音轨分配', '比赛二路设置 › 录制音轨', 'panels.py', 'full',
    '从录制设置中截取的音轨矩阵。每路可分配到 1–6 号音轨，右上角选择录制格式。'],
  ['match-launch', '比赛二路入口', '功能中心', 'plugin.py', 'compact',
    '从关注栏打开功能中心，可开启比赛二路或将入口固定到侧栏。'],
  ['match-float', '二路悬浮裁切', '来源行 › 裁取悬浮画面', 'floating.py', 'compact',
    '悬浮画面边角可调整大小。画面右上角提供选区、移动和关闭按钮。'],
  ['match-send', '二路弹幕发送控制台', '弹幕工具栏 › 展开发送', 'sending.py', 'compact',
    '单选一位主播时，右侧显示该平台的输入控件。头像用于选择目标，下方列表可取用已暂存的弹幕。'],
  ['match-batch', '二路批量发送', '弹幕控制台 › 多选主播', 'send_composers.py', 'compact',
    '选中多个主播时，弹幕控制台切换到批量输入。左侧头像标出收件人，输入框旁保留发送和暂存。'],
  ['match-danmaku', '二路弹幕观看设置', '二路播放格 › 弹幕观看设置', 'danmaku_settings.py', 'half',
    '弹出菜单提供显示区域、不透明度、字体大小、滚动速度、描边宽度和随屏幕缩放。'],
  ['match-clock', '计时器对齐', '来源行 › 计时器对齐', 'clock_dialog.py', 'half',
    '各路分别框选计时器和填写首帧时间。窗口底部可计算偏移和确认应用。'],
  ['match-settings', '比赛二路设置', '播放控制台 › 比赛二路设置', 'panels.py', 'full',
    '同一窗口提供回看预览大小、播放与画质、录制格式和音轨分配。'],
].map(([id, title, location, source, nativeSize, usage]) => ({
  id, title, location, source, nativeSize, usage, group: labMatchGroup, sheet: 'extension',
}))];

const labMatchImage = (id, theme) => `ui-control-match-qt/${id}-${theme}.png`;

function labMatchCapture(item, theme, detail = false) {
  const src = labMatchImage(item.id, theme);
  return `<figure class="lab-native-capture" data-match-capture="${item.id}">
    <div class="lab-native-frame"><img src="${src}" alt="${item.title}的 Windows Qt 截图"></div>
    ${detail ? `<figcaption><span>Windows Qt 实拍</span>
      <a class="lab-link" href="${src}" target="_blank" rel="noopener">查看原尺寸截图</a></figcaption>` : ''}
  </figure>`;
}

function labUpdateMatchCaptures(root, theme) {
  root.querySelectorAll('[data-match-capture]').forEach(capture => {
    const src = labMatchImage(capture.dataset.matchCapture, theme);
    const image = capture.querySelector('img');
    if (image.getAttribute('src') !== src) {
      image.src = src;
      const original = capture.querySelector('a');
      if (original) original.href = src;
    }
  });
}
