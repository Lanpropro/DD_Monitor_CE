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

const labMatchInteractive = id => id === 'match-console' || id === 'match-room';
const labMatchColors = [
  ['蓝色', '#38bdf8'], ['粉色', '#fb7185'], ['紫色', '#a78bfa'],
  ['绿色', '#4ade80'], ['黄色', '#fbbf24'], ['橙色', '#fb923c'],
];
const labMatchRoom = (name, avatar, color) => ({
  name, avatar, color, volume: 40, channels: 3, audible: true, chat: true, independent: false, assist: false, offset: 0,
});
const labMatchState = {
  rooms: [labMatchRoom('示例主路', '#5070fa', 0), labMatchRoom('示例副路', '#12b491', 1)],
  main: 0, automatic: true, compare: false, zoom: true, collapsed: false,
};

function labMountMatchWorkspace(host, item) {
  const state = labMatchState;
  const standalone = item.id === 'match-room';
  const glyph = key => labInventoryGlyph(labIconsById.get('match-' + key));
  const button = (action, label, content, pressed) => `<button type="button" data-match-action="${action}"
    aria-label="${label}" title="${label}"${pressed === undefined ? '' : ` aria-pressed="${pressed}"`}>${content}</button>`;
  const link = (target, label, content) => `<a href="#control-match-${target}" aria-label="${label}" title="${label}">${content}</a>`;
  const checkbox = (key, label, checked) => `<label><input type="checkbox" data-match-key="${key}"${checked ? ' checked' : ''}>${label}</label>`;
  host.innerHTML = `
    <div class="lab-match-workspace" aria-label="${item.title}">
      <div class="lab-match-scroll" tabindex="0" role="region" aria-label="二路控件，窄屏可横向滚动">
        <div class="lab-match-console">
          ${standalone ? '' : `<div class="lab-match-toolbar">
            <div>${checkbox('automatic', '自动对齐比赛画面', state.automatic)}
            ${checkbox('compare', '对照微调', state.compare)}</div>
            <div>${button('show-input', '展开直播间输入', '…')}
            ${button('show-input', '添加直播间', '添加直播间')}
            ${button('current', '加入当前观看的房间', '加入当前观看的房间')}
            ${link('settings', '比赛二路设置', labIcon('settings'))}
            ${button('collapse', '最小化播放控制台', glyph('minimize'))}</div>
          </div>
          <form class="lab-match-add" hidden>
            <input name="room" maxlength="160" required aria-label="房间号、平台前缀或直播链接" placeholder="房间号、平台前缀或直播链接">
            <button>添加直播间</button>${button('hide-input', '取消添加', '取消')}
          </form>
          <div class="lab-match-columns" aria-hidden="true"><span>直播来源</span><span>画面</span><span>声音</span>
            <span>弹幕</span><span>偏移</span><span>其他</span></div>`}
          <div class="lab-match-rows"></div>
        </div>
      </div>
      ${standalone ? '' : `<div class="lab-match-comparison" hidden>
        <header><span>偏移对照 · 全部直播间</span>${checkbox('zoom', '放大框选区域', state.zoom)}
          ${button('hide-compare', '收起对照', glyph('minimize'))}</header>
        <div class="lab-match-screens"></div>
      </div>`}
      <output class="lab-match-feedback" role="status"></output>
    </div>`;
  const root = host.querySelector('.lab-match-workspace');
  const scroll = root.querySelector('.lab-match-scroll');
  const rows = root.querySelector('.lab-match-rows');
  const comparison = root.querySelector('.lab-match-comparison');
  const form = root.querySelector('.lab-match-add');
  const report = message => { root.querySelector('output[role=status]').textContent = message; };

  function renderComparison() {
    if (!comparison) return;
    comparison.hidden = !state.compare;
    root.querySelector('[data-match-key=compare]').checked = state.compare;
    comparison.querySelector('[data-match-key=zoom]').checked = state.zoom;
    comparison.toggleAttribute('data-zoom', state.zoom);
    if (!state.compare) return;
    const screens = comparison.querySelector('.lab-match-screens');
    screens.replaceChildren(...state.rooms.map((room, index) => {
      const card = document.createElement('div');
      const heading = document.createElement('strong');
      heading.textContent = `${index === state.main ? '主画面' : '对照'} · ${room.name}`;
      if (index === state.main) heading.style.color = 'var(--lab-accent)';
      const frame = document.createElement('div');
      frame.textContent = index === state.main ? '主画面基准' : `当前偏移 ${room.offset.toFixed(2)} s`;
      frame.className = 'lab-match-screen';
      card.append(heading, frame);
      return card;
    }));
  }

  function syncRow(row, room, index) {
    const main = index === state.main;
    const mainButton = row.querySelector('[data-match-action=main]');
    mainButton.setAttribute('aria-pressed', main);
    mainButton.querySelector('span').textContent = main ? '主画面' : '设为主画面';
    mainButton.setAttribute('aria-label', main ? '主画面' : '设为主画面');
    mainButton.title = mainButton.getAttribute('aria-label');
    row.querySelector('[data-match-action=independent]').disabled = main;
    const audio = row.querySelector('[data-match-action=audio]');
    audio.setAttribute('aria-pressed', room.audible);
    audio.innerHTML = labIcon(room.audible ? 'qt-volume' : 'qt-mute')
      .replace('>LR</text>', `>${['', 'L', 'R', 'LR'][room.channels]}</text>`);
    for (const [action, pressed] of [['left', room.audible && !!(room.channels & 1)],
      ['right', room.audible && !!(room.channels & 2)], ['chat', room.chat],
      ['independent', room.independent], ['assist', room.assist]]) {
      row.querySelector(`[data-match-action=${action}]`).setAttribute('aria-pressed', pressed);
    }
    row.querySelector('.lab-match-hints').hidden = !room.assist;
    row.querySelector('.lab-match-room-status').textContent = room.independent ? '独立播放示例' : '未开始';
  }

  function renderRows() {
    const entries = standalone ? [state.rooms.find((_, index) => index !== state.main) || state.rooms[0]] : state.rooms;
    rows.innerHTML = entries.filter(Boolean).map(room => `<div class="lab-match-row" data-match-room="${state.rooms.indexOf(room)}">
      <div class="lab-match-identity"><span class="lab-match-avatar" style="--match-avatar:${room.avatar}">示</span>
        <div><div><strong></strong>${button('main', '设为主画面', glyph('main') + '<span></span>', false)}</div>
          <small class="lab-match-room-status"></small></div></div>
      <div>${link('float', '裁取悬浮画面', glyph('floating'))}${button('resync', '重新对齐', labIcon('qt-reconnect'))}</div>
      <div>${button('independent', '独立播放', glyph('independent'), false)}
        ${button('audio', '声音开关', '', true)}
        <input type="range" min="0" max="100" value="${room.volume}" aria-label="本路音量"><output>${room.volume}</output>
        <div class="lab-match-channels">${button('left', '左声道', 'L', true)}${button('right', '右声道', 'R', true)}</div>
      </div>
      <div>${button('chat', '弹幕开关', '<span>弹</span>', true)}
        <label class="lab-match-color" style="--match-color:${labMatchColors[room.color][1]}">
          <span aria-hidden="true"></span><select aria-label="弹幕来源颜色">${labMatchColors.map(([name], index) =>
            `<option value="${index}"${index === room.color ? ' selected' : ''}>${name}</option>`).join('')}</select>
        </label>
      </div>
      <div><div class="lab-match-step">${button('earlier', '提前 0.1 秒', '−')}
        <label><input type="number" min="-60" max="60" step="0.1" aria-label="本路偏移" value="${room.offset.toFixed(2)}"><span>s</span></label>
        ${button('later', '延后 0.1 秒', '+')}</div>
        ${button('assist', '辅助自动对齐', glyph('assist'), false)}
        ${link('clock', '计时器对齐', glyph('clock'))}
        <div class="lab-match-hints" hidden>${button('faster', '本路比主画面偏快', '偏快')}${button('slower', '本路比主画面偏慢', '偏慢')}</div>
      </div>
      <div>${button('region', '选择对照区域', glyph('region'))}${button('remove', '移除此路', '×')}</div>
    </div>`).join('') || '<p class="lab-match-empty">还没有直播来源，可添加示例房间。</p>';
    rows.querySelectorAll('[data-match-room]').forEach(row => {
      const index = Number(row.dataset.matchRoom);
      const room = state.rooms[index];
      row.querySelector('.lab-match-identity strong').textContent = room.name;
      syncRow(row, room, index);
      const range = row.querySelector('input[type=range]');
      range.style.setProperty('--match-volume', room.volume + '%');
    });
    renderComparison();
  }

  function updateOffset(field, room, value) {
    if (Number.isFinite(value)) room.offset = Number(galleryClamp(value, -60, 60).toFixed(2));
    field.value = room.offset.toFixed(2);
    state.compare = true;
  }

  function collapse(value) {
    state.collapsed = value;
    scroll.classList.toggle('lab-match-collapsed', value);
    const control = root.querySelector('[data-match-action=collapse]');
    const label = value ? '展开设置' : '最小化播放控制台';
    control.innerHTML = value ? label : glyph('minimize');
    control.setAttribute('aria-label', label);
    control.title = label;
    if (value) form.hidden = true;
  }

  function addRoom(name) {
    if (state.rooms.some(room => room.name === name)) {
      report('这个来源已在控制台中。');
      return false;
    }
    const index = state.rooms.length % labMatchColors.length;
    state.rooms.push(labMatchRoom(name, labMatchColors[index][1], index));
    renderRows();
    report(`已添加 ${name}`);
    return true;
  }

  form?.addEventListener('submit', event => {
    event.preventDefault();
    const field = form.elements.room;
    const name = field.value.trim();
    if (!name) {
      field.focus();
      return;
    }
    if (addRoom(name)) field.value = '';
  });
  root.addEventListener('input', event => {
    const row = event.target.closest('[data-match-room]');
    if (!row || event.target.type !== 'range') return;
    const room = state.rooms[Number(row.dataset.matchRoom)];
    room.volume = event.target.valueAsNumber;
    event.target.style.setProperty('--match-volume', room.volume + '%');
    row.querySelector('output').value = room.volume;
  });
  root.addEventListener('change', ({target}) => {
    const row = target.closest('[data-match-room]');
    if (target.dataset.matchKey) {
      state[target.dataset.matchKey] = target.checked;
    } else if (row && target.matches('select')) {
      const room = state.rooms[Number(row.dataset.matchRoom)];
      room.color = Number(target.value);
      target.parentElement.style.setProperty('--match-color', labMatchColors[room.color][1]);
    } else if (row && target.type === 'number') {
      const room = state.rooms[Number(row.dataset.matchRoom)];
      updateOffset(target, room, target.valueAsNumber);
    }
    renderComparison();
  });
  root.addEventListener('click', event => {
    const control = event.target.closest('[data-match-action]');
    if (!control) return;
    const action = control.dataset.matchAction;
    const row = control.closest('[data-match-room]');
    const index = Number(row?.dataset.matchRoom);
    const room = state.rooms[index];
    switch (action) {
      case 'show-input': form.hidden = false; form.elements.room.focus(); break;
      case 'hide-input': form.hidden = true; root.querySelector('[data-match-action=show-input]').focus(); break;
      case 'current': addRoom('当前观看的示例房间'); break;
      case 'collapse': collapse(!state.collapsed); break;
      case 'hide-compare': state.compare = false; root.querySelector('[data-match-key=compare]').focus(); break;
      case 'main':
        state.main = index;
        room.independent = false;
        rows.querySelectorAll('[data-match-room]').forEach(current => {
          const index = Number(current.dataset.matchRoom);
          syncRow(current, state.rooms[index], index);
        });
        report(`已将 ${room.name} 设为主画面`);
        break;
      case 'audio': room.audible = !room.audible; break;
      case 'left':
      case 'right':
        room.channels = (room.audible ? room.channels : 0) ^ (action === 'left' ? 1 : 2);
        room.audible = Boolean(room.channels);
        if (!room.channels) room.channels = 3;
        break;
      case 'chat':
      case 'independent':
      case 'assist': room[action] = !room[action]; break;
      case 'earlier':
      case 'later': updateOffset(row.querySelector('input[type=number]'), room, room.offset + (action === 'later' ? .1 : -.1)); break;
      case 'resync': report(`${room.name} · 已请求重新对齐示例`); break;
      case 'region':
        state.compare = true;
        state.zoom = true;
        report(standalone ? '已标记示例对照区域，可返回播放控制台查看。' : '已开启示例画面对照');
        break;
      case 'faster':
      case 'slower': report(`${room.name} · 已标记${action === 'faster' ? '偏快' : '偏慢'}`); break;
      case 'remove':
        state.rooms.splice(index, 1);
        if (index < state.main) state.main--;
        else if (index === state.main) state.main = 0;
        renderRows();
        (rows.querySelector('button') || root.querySelector('[data-match-action=show-input]') || scroll).focus();
        report(`已移除 ${room.name}`);
        return;
    }
    if (row) syncRow(row, room, index);
    renderComparison();
  });

  renderRows();
  if (!standalone) collapse(state.collapsed);
}
