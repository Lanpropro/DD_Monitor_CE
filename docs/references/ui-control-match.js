const labExtensions = [{
  id: 'icon-control', title: '通用图标按钮', location: '本体与比赛二路', group: '图标与通用控件',
  width: 320, height: 34, radius: 8, area: 'settings', sheet: 'extension',
  source: 'ddm/sidebar_navigation.py',
  usage: '选取图标后试用同一按钮。详情可调整尺寸、颜色和交互状态，并按分组查看图标来源。',
}, ...[
  ['match-launch', '比赛二路入口', '功能中心', 'plugin.py', '体验打开和关闭插件工作区。'],
  ['match-console', '二路播放控制台', '比赛二路 › 播放控制台', 'viewer_ui.py', '添加示例来源，切换自动对齐和缓存余量。'],
  ['match-room', '二路来源控制行', '播放控制台 › 每路来源', 'room_widgets.py', '切换主画面与独立播放，调整声道、相对偏移，并确认加入。'],
  ['match-compare', '二路画面对照', '播放控制台 › 画面对照', 'comparison.py', '切换对照来源，框选后放大查看并继续微调。'],
  ['match-float', '二路悬浮裁切', '来源行 › 裁取悬浮画面', 'floating.py', '调节悬浮预览大小，恢复或关闭样例。'],
  ['match-clock', '计时器对齐', '来源行 › 计时器对齐', 'clock_dialog.py', '按获取画面、框选、核对计时、计算和应用的顺序试用。'],
  ['match-replay', '二路回看时间线', '二路画面 › 回看', 'replay.py', '试用进度拖动、时间跳转和返回直播。'],
  ['match-record', '二路分音轨录制', '播放控制台 › 录制', 'recording_control.py', '选择容器和音轨，试用开始、停止及状态变化。'],
  ['match-send', '二路弹幕发送控制台', '弹幕工具栏 › 展开发送', 'sending.py', '选择一个示例来源，暂存文字和模拟发送。'],
  ['match-batch', '二路批量发送', '发送控制台 › 批量发送', 'send_composers.py', '选择多个目标，试用取消和发送结果。'],
  ['match-danmaku', '二路弹幕观看设置', '二路播放格 › 弹幕观看设置', 'danmaku_settings.py', '试调显示区域、透明度、字号、速度、描边和屏幕缩放。'],
  ['match-settings', '比赛二路设置', '播放控制台 › 比赛二路设置', 'panels.py', '试选缓存余量、画中画画质、回看预览大小及音轨。'],
].map(([id, title, location, source, usage]) => ({
  id, title, location, source, usage, group: '比赛二路插件', width: 320, height: 30, radius: 8,
  area: 'settings', sheet: 'extension', sourceLink: labMatchSource(source),
}))];

function labMatchExample(item, popupId) {
  const button = (label, action, glyph = '') => {
    const attrs = `data-match-action="${action}"`;
    if (!glyph) return labButton(label, '', label, attrs);
    return labInventoryButton(labIconsById.get('match-' + glyph), attrs, label);
  };
  const check = (label, checked = false) => `<label><input type="checkbox" ${checked ? 'checked' : ''}> ${label}</label>`;
  const input = (label, attr = '', value = '') => `<input class="lab-control" aria-label="${label}" placeholder="${label}" value="${value}" ${attr}>`;
  const select = (label, options) => `<label class="lab-match-field"><span>${label}</span>${labSelect(label, options)}</label>`;
  const row = (...children) => `<div class="lab-match-row">${children.join('')}</div>`;
  const screen = (label, selectable = false) => `<div class="lab-match-screen" aria-label="${label}">
    <span>${label}</span>${selectable ? '<i data-match-box hidden></i>' : ''}</div>`;
  const info = (content, attrs = '') => `<output ${attrs}>${content}</output>`;
  const buffer = () => select('缓存余量', ['缓存 2 秒 · 低延迟', '缓存 5 秒 · 均衡', '缓存 8 秒 · 抗波动']);
  const panel = (trigger, content) => `<button type="button" class="lab-control" popovertarget="${popupId}" data-primary>${trigger}</button>
    <div id="${popupId}" class="lab-extra-popup lab-match-popover" popover aria-label="${item.title}">${content}</div>`;
  let content;
  switch (item.id) {
    case 'match-launch':
      content = row(button('比赛二路同步', 'launch', 'entry'), info('工作区未打开', 'data-match-output')); break;
    case 'match-console':
      content = row(input('房间号、平台前缀或直播链接', 'data-match-input'), button('添加直播间', 'add'))
        + row(check('自动对齐', true), button('加入当前观看的房间', 'add-current'))
        + buffer() + info('2 路示例来源', 'data-match-output'); break;
    case 'match-room':
      content = row(button('主画面', 'toggle', 'main'), check('L', true), check('R', true),
        button('独立播放', 'toggle', 'independent'), button('重新匹配', 'message', 'resync'), button('辅助自动对齐', 'message', 'assist'))
        + row(check('画面弹幕', true), labRange('本路音量', 0, 100, 60, '%'))
        + select('弹幕来源颜色', ['默认', '蓝', '粉'])
        + row(button('提前 0.1 秒', 'offset-down'), info('+0.0 s', 'data-match-output'), button('延后 0.1 秒', 'offset-up'))
        + row(button('确认对齐并加入', 'confirm')); break;
    case 'match-compare':
      content = select('对照来源', ['示例副路 A', '示例副路 B'])
        + row(screen('主画面'), screen('对照预览', true))
        + row(button('选择对照区域', 'region', 'region'), check('放大框选区域'), button('收起对照', 'collapse', 'minimize')); break;
    case 'match-float':
      content = screen('悬浮画面预览', true) + labRange('悬浮大小', 40, 100, 80, '%', true)
        + row(button('重新框选', 'region', 'floating'), button('使用整个画面', 'reset-region'), button('关闭', 'collapse')); break;
    case 'match-clock':
      content = select('计时方式', ['倒计时', '正计时'])
        + screen('计时器预览', true) + row(button('获取画面', 'message'), button('框选计时器', 'region', 'region'), button('采样并识别', 'message'))
        + row(input('首帧时间', 'data-match-input', '12:05'), button('计算偏移', 'calculate'), button('确认应用', 'confirm-clock'))
        + info('等待采样', 'data-match-output'); break;
    case 'match-replay':
      content = screen('回看目标预览') + labRange('回看进度', 0, 120, 90, ' s', true)
        + row(input('跳转秒数', 'data-match-input inputmode="numeric"', '90'), button('跳转', 'seek'), button('返回直播', 'live', 'live')); break;
    case 'match-record':
      content = select('录制容器', ['MKV', 'MP4'])
        + row(check('主画面音轨', true), check('副路音轨', true), button('开始录制', 'record'))
        + info('等待录制', 'data-match-output'); break;
    case 'match-send':
      content = select('目标直播间', ['示例主路', '示例副路'])
        + row(input('输入示例弹幕', 'data-match-input'), button('暂存当前输入', 'save', 'save'), button('模拟发送', 'send'))
        + info('暂无暂存', 'data-match-output'); break;
    case 'match-batch':
      content = row(check('示例主路', true), check('示例副路'))
        + row(input('输入示例弹幕', 'data-match-input'), button('取消', 'cancel'), button('模拟发送', 'batch')); break;
    case 'match-danmaku':
      content = panel('弹幕观看设置', labDanmakuParams
        .map(values => `<div class="lab-match-field"><span>${values[0]}</span>${labRange(...values)}</div>`).join('')
        + check('弹幕随屏幕缩放', true)); break;
    case 'match-settings':
      content = panel('比赛二路设置', buffer() + select('画中画画质', ['流畅优先：直接裁切', '轻量增强：放大与轻锐化'])
        + select('录制格式', ['MKV', 'MP4']) + labRange('回看预览大小', 10, 60, 22, '%')
        + row(check('主画面音轨', true), check('副路音轨', true), button('关闭', 'close-popover'))); break;
  }
  return `<div class="lab-extension lab-match-demo">${content}</div>`;
}

function labBindMatchExample(host, report) {
  let count = 2;
  let offset = 0;
  const query = selector => host.querySelector(selector);
  const output = query('[data-match-output]');
  const screen = query('.lab-match-screen:has([data-match-box])');
  const preview = host.dataset.labDemo === 'match-compare' ? screen.parentElement : screen;
  const input = query('[data-match-input]');
  const box = query('[data-match-box]');
  function setRange(range, value) {
    range.value = value;
    range.dispatchEvent(new Event('input', {bubbles: true}));
  }
  host.addEventListener('input', ({target}) => {
    if (target.type !== 'range') return;
    target.style.setProperty('--lab-level', `${(target.value - target.min) * 100 / (target.max - target.min)}%`);
    target.nextElementSibling.textContent = target.value + target.nextElementSibling.dataset.unit;
    if (host.dataset.labDemo === 'match-float') screen.style.width = `${target.value}%`;
  });
  host.addEventListener('change', ({target}) => {
    if (target.getAttribute('aria-label') === '对照来源') screen.querySelector('span').textContent = target.value;
    if (target.type === 'checkbox' && target.closest('label').textContent.trim() === '放大框选区域') {
      screen.toggleAttribute('data-match-zoom', target.checked);
      screen.querySelector('span').textContent = target.checked ? '已放大示例选区' : query('select').value;
    }
  });
  host.addEventListener('click', event => {
    const button = event.target.closest('[data-match-action]');
    if (!button) return;
    const action = button.dataset.matchAction;
    const label = button.getAttribute('aria-label') || button.textContent;
    switch (action) {
      case 'launch':
      case 'toggle':
      case 'record': {
        const active = button.getAttribute('aria-pressed') !== 'true';
        button.setAttribute('aria-pressed', active);
        if (action === 'launch') output.textContent = active ? '工作区已打开' : '工作区未打开';
        if (action === 'record') {
          button.querySelector('.lab-label').textContent = active ? '停止录制' : '开始录制';
          output.textContent = active ? '模拟录制中' : '模拟录制已停止';
        }
        report(active ? `已启用 ${label}` : `已关闭 ${label}`);
        break;
      }
      case 'offset-down':
      case 'offset-up':
        offset = galleryClamp(offset + (action === 'offset-up' ? 1 : -1), -600, 600);
        output.textContent = `${offset >= 0 ? '+' : ''}${(offset / 10).toFixed(1)} s`;
        break;
      case 'add':
      case 'add-current':
        if (action === 'add' && !input.value.trim()) { report('请输入房间号或直播链接'); break; }
        output.textContent = `${++count} 路示例来源`;
        input.value = '';
        break;
      case 'region':
      case 'reset-region':
        box.hidden = action === 'reset-region' || !box.hidden;
        preview.hidden = false;
        report(box.hidden ? '已恢复整个画面' : '已显示示例选区');
        break;
      case 'collapse':
        preview.hidden = !preview.hidden;
        report(preview.hidden ? '已收起示例预览' : '已展开示例预览');
        break;
      case 'calculate':
        output.textContent = /^\d{1,3}:[0-5]\d$/.test(input.value) ? '建议偏移 +1.2 s' : '请输入有效的分:秒';
        break;
      case 'confirm-clock':
        report(output.textContent.startsWith('建议') ? '已应用示例偏移 +1.2 s' : '请先计算偏移');
        break;
      case 'seek':
      case 'live': {
        const range = query('input[type=range]');
        if (action === 'seek' && (!input.value.trim() || !Number.isFinite(Number(input.value)))) {
          report('请输入有效秒数');
          break;
        }
        setRange(range, action === 'live' ? range.max : input.value);
        input.value = range.value;
        report(action === 'live' ? '已返回示例直播' : `已跳转 ${range.value} 秒`);
        break;
      }
      case 'save':
        if (input.value.trim()) output.textContent = `已暂存：${input.value.trim()}`;
        break;
      case 'cancel':
        input.value = '';
        report('已取消');
        break;
      case 'close-popover':
        button.closest('[popover]').hidePopover();
        break;
      case 'send':
      case 'batch': {
        const targets = action === 'batch' ? host.querySelectorAll('input[type=checkbox]:checked').length : 1;
        if (!targets || !input.value.trim()) { report('请选择目标并填写示例弹幕'); break; }
        input.value = '';
        report(`已模拟发送至 ${targets} 路`);
        break;
      }
      default:
        report(`已触发 ${label}`);
    }
  });
}
