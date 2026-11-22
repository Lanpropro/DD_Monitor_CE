const gallerySpringDefaults = Object.freeze({ duration: 0.5, bounce: 0.16 });
const galleryReducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const gallerySegmentSwitch = document.getElementById('segment-motion');
const galleryClamp = (value, min, max) => Math.max(min, Math.min(max, value));

const galleryStepButtons = 'button[data-lab-step], .stepper button[data-step], .lab-qt-number-step button, .lab-match-step > button';
let galleryStopStepHold;
let galleryRepeatedStep;

document.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.button !== 0) return;
  galleryStopStepHold?.();
  galleryRepeatedStep = null;
  const button = event.target.closest(galleryStepButtons);
  if (!button || button.matches(':disabled')) return;

  const listeners = new AbortController();
  const options = { signal: listeners.signal };
  let delay = 160;
  let timer = setTimeout(repeat, 340);
  function stop() {
    clearTimeout(timer);
    listeners.abort();
    galleryStopStepHold = null;
  }
  function repeat() {
    if (!button.isConnected || button.matches(':disabled') || button.closest('[hidden]')) {
      stop();
      return;
    }
    galleryRepeatedStep = button;
    button.click();
    timer = setTimeout(repeat, delay);
    delay = Math.max(48, delay * .75);
  }
  galleryStopStepHold = stop;
  for (const type of ['pointerup', 'pointercancel']) {
    window.addEventListener(type, end => { if (end.pointerId === event.pointerId) stop(); }, options);
  }
  window.addEventListener('pointermove', move => {
    if (move.pointerId !== event.pointerId) return;
    const { left, right, top, bottom } = button.getBoundingClientRect();
    if (move.clientX < left || move.clientX > right || move.clientY < top || move.clientY > bottom) stop();
  }, options);
  window.addEventListener('blur', stop, options);
});

document.addEventListener('click', event => {
  // A long press already activated the button through its regular click handler.
  if (event.detail > 0 && galleryRepeatedStep && event.target.closest('button') === galleryRepeatedStep) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

function gallerySpringStep(state, target, { duration, bounce }, elapsed) {
  const omega = 2 * Math.PI / duration;
  const zeta = 1 - bounce;
  const count = Math.ceil(elapsed / Math.min(1 / 120, 0.2 / omega));
  const dt = elapsed / count;
  for (let i = 0; i < count; i++) {
    const acceleration = -2 * zeta * omega * state.velocity - omega * omega * (state.position - target);
    state.velocity += acceleration * dt;
    state.position += state.velocity * dt;
  }
}

class GalleryMotion {
  constructor(element, position, paint) {
    this.element = element;
    this.position = position;
    this.velocity = 0;
    this.paint = paint;
    this.frame = null;
  }

  pause() {
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
  }

  place(position, velocity = 0) {
    this.pause();
    this.position = position;
    this.velocity = velocity;
    this.paint(position);
  }

  spring(target, settings) {
    if (settings.duration === 0 || galleryReducedMotion.matches) {
      this.place(target);
      return;
    }
    this.target = target;
    this.settings = settings;
    if (this.position !== target || this.velocity !== 0) this.start();
  }

  coast(min, max) {
    this.settings = null;
    this.bounds = [min, max];
    if (!galleryReducedMotion.matches && Math.abs(this.velocity) >= 0.01) this.start();
    else this.place(this.position);
  }

  start() {
    if (this.frame !== null) return;
    this.time = performance.now();
    this.frame = requestAnimationFrame(this.tick);
  }

  tick = time => {
    this.frame = null;
    if (!this.element.isConnected) return;
    const dt = galleryClamp((time - this.time) / 1000, 0, 0.08);
    this.time = Math.max(this.time, time);
    if (this.settings) {
      if (galleryReducedMotion.matches) return this.place(this.target);
      if (dt > 0) gallerySpringStep(this, this.target, this.settings, dt);
      if (Math.abs(this.position - this.target) < 0.001 && Math.abs(this.velocity) < 0.01) {
        return this.place(this.target);
      }
    } else {
      if (galleryReducedMotion.matches) return this.place(this.position);
      const decay = Math.exp(-8 * dt);
      const next = this.position + this.velocity * (1 - decay) / 8;
      const bounded = galleryClamp(next, ...this.bounds);
      this.velocity *= decay;
      if (next !== bounded || Math.abs(this.velocity) < 0.01) return this.place(bounded);
      this.position = bounded;
    }
    this.paint(this.position);
    this.frame = requestAnimationFrame(this.tick);
  };
}

function galleryBindSwitch(input, getDuration, stretchThumb = false) {
  const track = input.nextElementSibling;
  const offset = '--lab-thumb-offset';
  const stretch = '--lab-thumb-stretch';
  track.dataset.springThumb = '';
  const motion = new GalleryMotion(track, Number(input.checked), position => {
    if (position === Number(input.checked) && motion.velocity === 0) {
      track.style.removeProperty(offset);
      track.style.removeProperty(stretch);
    } else {
      track.style.setProperty(offset, `${galleryClamp(position, 0, 1) * 100}%`);
      if (stretchThumb) track.style.setProperty(stretch, 1 + Math.min(0.18, Math.abs(motion.velocity) * 0.025));
    }
  });
  let pointer = false;
  input.addEventListener('click', event => { pointer = event.detail > 0; });
  input.addEventListener('change', () => {
    const target = Number(input.checked);
    if (pointer) {
      if (motion.frame === null && !track.style.getPropertyValue(offset)) motion.position = 1 - target;
      motion.paint(motion.position);
      motion.spring(target, { duration: getDuration(), bounce: 0 });
    } else {
      motion.place(target);
    }
    pointer = false;
  });
}

function galleryTrackDrag(element, { canStart, grab, move, release, threshold = 4, axis = 'x', grabOnPress = false }) {
  let gesture;
  let suppressClick = false;
  const point = event => ({ x: event.clientX, y: event.clientY, time: event.timeStamp });

  element.addEventListener('pointerdown', event => {
    if (gesture || !event.isPrimary || event.button !== 0 || !canStart(event)) return;
    suppressClick = false;
    const origin = point(event);
    gesture = { id: event.pointerId, origin, last: origin, vx: 0, vy: 0, moved: false };
    event.target.closest('button').setPointerCapture(event.pointerId);
    if (grabOnPress || threshold === 0) grab(event);
  });

  function update(event) {
    if (gesture?.id !== event.pointerId) return;
    const next = point(event);
    const dx = next.x - gesture.origin.x;
    const dy = next.y - gesture.origin.y;
    const distance = axis === 'both' ? Math.hypot(dx, dy) : Math.abs(axis === 'y' ? dy : dx);
    if (!gesture.moved && (threshold ? distance < threshold : dx === 0 && dy === 0)) return;
    if (!gesture.moved && threshold && !grabOnPress) grab(event);
    gesture.moved = true;
    const dt = Math.max(0.008, (next.time - gesture.last.time) / 1000);
    gesture.vx = (next.x - gesture.last.x) / dt;
    gesture.vy = (next.y - gesture.last.y) / dt;
    gesture.last = next;
    move(dx, dy, gesture.vx, gesture.vy);
  }

  function finish(event) {
    if (gesture?.id !== event.pointerId) return;
    const cancelled = event.type !== 'pointerup';
    if (!cancelled && (event.clientX !== gesture.last.x || event.clientY !== gesture.last.y)) update(event);
    const { last, moved, vx, vy } = gesture;
    gesture = undefined;
    suppressClick = moved;
    if (!moved && threshold && !grabOnPress) return;
    const age = Math.max(0, (event.timeStamp - last.time) / 1000);
    const decay = cancelled || age > 0.1 ? 0 : Math.exp(-20 * age);
    release(vx * decay, vy * decay, cancelled, moved);
  }

  element.addEventListener('pointermove', update);
  element.addEventListener('pointerup', finish);
  element.addEventListener('pointercancel', finish);
  element.addEventListener('lostpointercapture', finish);
  element.addEventListener('click', event => {
    if (!suppressClick || event.detail === 0) return;
    suppressClick = false;
    event.stopImmediatePropagation();
    event.preventDefault();
  }, true);
}

function galleryBindFollowOrder(list, getDuration, report) {
  // One unit is 100 pixels, so the spring's 0.001-unit settle tolerance is subpixel.
  const unit = 100;
  const motions = new Map([...list.children].map(row => [
    row, new GalleryMotion(row, 0, offset => { row.style.transform = `translateY(${offset * unit}px)`; }),
  ]));
  let drag;

  function reorder(rows, source, target) {
    if (source === target) return;
    const handle = rows[source].querySelector('button');
    if (source < target) rows[target].after(rows[source]);
    else rows[target].before(rows[source]);
    handle.focus({ preventScroll: true });
    report('已调整关注卡片顺序');
  }

  function finish(vy, cancelled) {
    if (!drag) return;
    const { rows, source, target, offsets, row, settings } = drag;
    const selected = motions.get(row);
    const top = offsets[source] + selected.position * unit;
    const movingPastEdge = (vy < 0 && top <= offsets[0]) || (vy > 0 && top >= offsets.at(-1));
    selected.velocity = cancelled || movingPastEdge ? 0 : galleryClamp(vy / unit, -8, 8);
    if (!cancelled) reorder(rows, source, target);
    const newOffsets = rows.map(card => card.offsetTop);
    rows.forEach((card, index) => {
      const motion = motions.get(card);
      motion.position += (offsets[index] - newOffsets[index]) / unit;
      motion.paint(motion.position);
      motion.spring(0, settings);
    });
    delete row.dataset.followDragging;
    drag = null;
  }

  galleryTrackDrag(list, {
    axis: 'y',
    canStart: event => Boolean(event.target.closest('[data-follow-grab]:enabled')),
    grab: event => {
      const handle = event.target.closest('[data-follow-grab]');
      const row = handle.parentElement;
      const rows = [...list.children];
      const source = rows.indexOf(row);
      const motion = motions.get(row);
      motion.pause();
      const offsets = rows.map(card => card.offsetTop);
      drag = { row, handle, pointer: event.pointerId, rows, source, target: source, offsets,
        centers: rows.map((card, index) => offsets[index] + card.offsetHeight / 2), start: motion.position * unit,
        height: row.offsetHeight, settings: { duration: getDuration(), bounce: 0 } };
      row.dataset.followDragging = '';
    },
    move: (dx, dy) => {
      if (!drag) return;
      const { row, rows, source, offsets, centers, settings, start, height } = drag;
      const top = galleryClamp(offsets[source] + start + dy, offsets[0], offsets.at(-1));
      const center = top + height / 2;
      motions.get(row).place((top - offsets[source]) / unit);
      // Hit testing uses stable row midpoints, even while their painted positions are moving.
      // The clamped top and bottom positions always denote the first and last slots.
      let target = 0;
      if (top === offsets.at(-1)) target = rows.length - 1;
      else if (top > offsets[0]) {
        target = centers.filter((midpoint, index) => index !== source && center >= midpoint).length;
      }
      if (target === drag.target) return;
      drag.target = target;
      const order = [...rows];
      order.splice(source, 1);
      order.splice(target, 0, row);
      order.forEach((card, index) => {
        if (card !== row) motions.get(card).spring((offsets[index] - offsets[rows.indexOf(card)]) / unit, settings);
      });
    },
    release: (vx, vy, cancelled) => finish(vy, cancelled),
  });

  list.addEventListener('keydown', event => {
    const handle = event.target.closest('[data-follow-grab]');
    if (!handle) return;
    if (drag && event.key === 'Escape') {
      event.preventDefault();
      const { handle: captured, pointer } = drag;
      finish(0, true);
      if (captured.hasPointerCapture(pointer)) captured.releasePointerCapture(pointer);
    } else if (!drag && event.altKey && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      const rows = [...list.children];
      const source = rows.indexOf(handle.parentElement);
      const target = galleryClamp(source + (event.key === 'ArrowDown' ? 1 : -1), 0, rows.length - 1);
      motions.forEach(motion => motion.place(0));
      reorder(rows, source, target);
    }
  });
}

function galleryBindPaneSwap(grid, getDuration, report) {
  const unit = 100;
  const position = pane => [pane.offsetLeft, pane.offsetTop];
  const motions = new Map([...grid.children].map(pane => {
    const paint = () => {
      pane.style.transform = `translate(${x.position * unit}px, ${y.position * unit}px)`;
    };
    const x = new GalleryMotion(pane, 0, paint);
    const y = new GalleryMotion(pane, 0, paint);
    return [pane, [x, y]];
  }));
  let drag;

  function swap(source, target) {
    const order = [...grid.children];
    const from = order.indexOf(source), to = order.indexOf(target);
    [order[from], order[to]] = [order[to], order[from]];
    grid.append(...order);
    source.focus({ preventScroll: true });
    report('已交换画面位置');
  }

  function finish(vx, vy, cancelled, moved) {
    if (!drag) return;
    const { source, target, settings } = drag;
    if (target) delete target.dataset.pipDrop;
    delete grid.dataset.pipTarget;
    delete source.dataset.pipDragging;
    drag = null;
    const destination = moved && !cancelled ? target : null;
    const affected = destination ? [source, destination] : [source];
    const before = affected.map(position);
    if (destination) swap(source, destination);
    const after = affected.map(position);
    if (moved) {
      const speeds = destination ? [vx, vy] : [0, 0];
      motions.get(source).forEach((axis, i) => { axis.velocity = galleryClamp(speeds[i] / unit, -8, 8); });
    }
    affected.forEach((pane, index) => {
      const axes = motions.get(pane);
      axes.forEach((axis, i) => {
        axis.position += (before[index][i] - after[index][i]) / unit;
      });
      axes[0].paint();
      axes.forEach(axis => axis.spring(0, settings));
    });
  }

  function cancel() {
    if (!drag) return;
    const { source, pointer } = drag;
    finish(0, 0, true, true);
    if (source.hasPointerCapture(pointer)) source.releasePointerCapture(pointer);
  }

  galleryTrackDrag(grid, {
    axis: 'both',
    grabOnPress: true,
    canStart: event => Boolean(event.target.closest('button:enabled')),
    grab: event => {
      const source = event.target.closest('button');
      const bounds = grid.getBoundingClientRect();
      const axes = motions.get(source);
      axes.forEach(axis => axis.pause());
      drag = {
        source, pointer: event.pointerId,
        x: event.clientX - bounds.left - grid.clientLeft,
        y: event.clientY - bounds.top - grid.clientTop,
        start: axes.map(axis => axis.position),
        slots: [...grid.children].filter(pane => pane !== source).map(pane => {
          const [left, top] = position(pane);
          return { pane, left, top, right: left + pane.offsetWidth, bottom: top + pane.offsetHeight };
        }),
        settings: { duration: getDuration(), bounce: 0.08 },
      };
    },
    move: (dx, dy) => {
      if (!drag) return;
      const { source, start, slots, x, y } = drag;
      source.dataset.pipDragging = '';
      motions.get(source).forEach((axis, i) => axis.place(start[i] + (i ? dy : dx) / unit));
      const pointerX = x + dx, pointerY = y + dy;
      const slot = slots.find(slot => pointerX >= slot.left && pointerX < slot.right
        && pointerY >= slot.top && pointerY < slot.bottom);
      const target = slot?.pane;
      if (target === drag.target) return;
      if (drag.target) delete drag.target.dataset.pipDrop;
      if (target) {
        target.dataset.pipDrop = '';
        grid.style.setProperty('--pip-drop-inset', `${slot.top}px auto auto ${slot.left}px`);
        grid.style.setProperty('--pip-drop-width', `${slot.right - slot.left}px`);
        grid.style.setProperty('--pip-drop-height', `${slot.bottom - slot.top}px`);
        grid.dataset.pipTarget = '';
      } else delete grid.dataset.pipTarget;
      drag.target = target;
    },
    release: finish,
  });

  const reset = () => {
    cancel();
    motions.forEach(axes => axes.forEach(axis => axis.place(0)));
  };
  grid.addEventListener('keydown', event => {
    const source = event.target.closest('button');
    if (event.key === 'Escape' && drag) {
      event.preventDefault();
      cancel();
    } else if (source && !drag && event.altKey && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      const target = event.key === 'ArrowDown' ? source.nextElementSibling : source.previousElementSibling;
      if (target) {
        reset();
        swap(source, target);
      }
    }
  });
  return reset;
}

const gallerySegments = new WeakMap();
const gallerySlideEnabled = () => gallerySegmentSwitch.checked && !galleryReducedMotion.matches;

function galleryBindSegment(group, buttonSelector, indicator, select) {
  const buttons = [...group.querySelectorAll(buttonSelector)];
  const index = () => buttons.findIndex(button => button.getAttribute('aria-pressed') === 'true');
  const motion = new GalleryMotion(indicator, index(), position => {
    indicator.style.transform = `translateX(calc(${position} * (100% + var(--lab-choice-gap, 3px))))`;
  });
  const settings = { ...gallerySpringDefaults };
  gallerySegments.set(group, { settings, motion, index });
  let origin;
  let stride;
  galleryTrackDrag(group, {
    canStart: event => gallerySlideEnabled() && settings.duration > 0 && event.target.closest('button:enabled'),
    grab: () => {
      motion.pause();
      origin = motion.position;
      stride = buttons[1].getBoundingClientRect().x - buttons[0].getBoundingClientRect().x;
    },
    move: (dx, dy, vx) => {
      if (!gallerySlideEnabled() || !settings.duration) return;
      const raw = origin + dx / stride;
      const edge = galleryClamp(raw, 0, buttons.length - 1);
      const outside = raw !== edge;
      motion.place(edge + (raw - edge) * 0.2, vx / stride * (outside ? 0.2 : 1));
    },
    release: (vx, vy, cancelled) => {
      motion.velocity = vx / stride * (motion.position < 0 || motion.position > buttons.length - 1 ? 0.2 : 1);
      const target = cancelled ? index() : galleryClamp(Math.round(motion.position), 0, buttons.length - 1);
      select(buttons[target], true);
    },
  });
}

function gallerySelectSegment(group, selected, pointer) {
  const controller = gallerySegments.get(group);
  const { motion, settings } = controller;
  [...group.querySelectorAll('button')].forEach(button => button.setAttribute('aria-pressed', button === selected));
  const target = controller.index();
  if (pointer && gallerySlideEnabled()) motion.spring(target, settings);
  else motion.place(target);
}

gallerySegmentSwitch.addEventListener('change', () => {
  if (gallerySegmentSwitch.checked) return;
  document.querySelectorAll('.lab-choice, [data-example-segment]').forEach(group => {
    const controller = gallerySegments.get(group);
    if (controller) controller.motion.place(controller.index());
  });
});
