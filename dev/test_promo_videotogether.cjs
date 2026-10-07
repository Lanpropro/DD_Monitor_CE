// Regression fixture: VideoTogether 3.0.23 VideoClicked/AddVideoListener/isLimited.
// Matches the installed extension's play/pause/seeked hook and 15-per-5s limit.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const html = readFileSync(join(__dirname,
  '../videos/dd-monitor-ce-plugins-promo/index.html'), 'utf8');
const guard = html.match(/<script id="preview-media-isolation">([\s\S]*?)<\/script>/)[1];
const types = ['play', 'pause', 'seeked'];

function fixture() {
  const videos = [new EventTarget(), new EventTarget()];
  const outside = new EventTarget();
  const errors = [];
  const logger = {error: message => errors.push(message)};
  const originalError = logger.error;
  const window = {};
  let mutation;
  let frameworkEvents = 0;
  const document = {documentElement: {}, querySelectorAll(selector) {
    assert.equal(selector, '#root video');
    return videos;
  }};
  function attach(video) {
    for (const type of types)
      video.addEventListener(type, () => frameworkEvents++);
  }
  videos.forEach(attach);
  function extension() {
    const queue = [];
    const ext = {VideoClickedListener() {
      while (queue.length && queue[0] < Date.now()/1000 - 5) queue.shift();
      if (queue.length > 15) { logger.error('limited'); return; }
      queue.push(Date.now()/1000);
    }, AddVideoListener(video) {
      for (const type of types) video.addEventListener(type, ext.VideoClickedListener, false);
    }};
    [...videos, outside].forEach(ext.AddVideoListener);
    window.videoTogetherExtension = ext;
    return ext;
  }
  function install() {
    runInNewContext(guard, {window, document, console: logger, queueMicrotask,
      MutationObserver: class {
        constructor(callback) { mutation = callback; }
        observe(target, options) {
          assert.equal(target, document.documentElement);
          assert.equal(options.childList, true);
          assert.equal(options.subtree, true);
        }
      }});
  }
  function burst(video, count = 60) {
    for (let i=0; i<count; i++) video.dispatchEvent(new Event(types[i%3]));
  }
  return {videos, outside, errors, logger, originalError, extension, install, burst,
    attach, mutation: () => mutation(), frameworkEvents: () => frameworkEvents};
}

test('unprotected playback and seeking reproduce the extension limited error', () => {
  const f = fixture(); f.extension(); f.burst(f.videos[0]);
  assert.ok(f.errors.includes('limited'));
});

test('existing extension hooks are removed without blocking framework events', () => {
  const f = fixture(); f.extension(); f.install();
  f.videos.forEach(video => { f.burst(video); assert.equal(video.VideoTogetherDisabled, true); });
  assert.deepEqual(f.errors, []);
  assert.equal(f.frameworkEvents(), 120);
  assert.equal(f.logger.error, f.originalError);
  f.logger.error('real composition error');
  assert.deepEqual(f.errors, ['real composition error']);
});

test('extension injected after the composition is also excluded', async () => {
  const f = fixture(); f.install(); f.extension(); f.mutation();
  await Promise.resolve();
  f.burst(f.videos[0]); assert.deepEqual(f.errors, []);
});

for (const order of ['before', 'after']) {
  test(`mounted scene video is excluded when extension observer runs ${order}`, async () => {
    const f = fixture(); const ext = f.extension(); f.install();
    const video = new EventTarget(); f.videos.push(video); f.attach(video);
    if (order === 'before') ext.AddVideoListener(video);
    f.mutation();
    if (order === 'after') ext.AddVideoListener(video);
    await Promise.resolve();
    f.burst(video);
    assert.equal(video.VideoTogetherDisabled, true);
    assert.deepEqual(f.errors, []); assert.equal(f.frameworkEvents(), 60);
  });
}

test('other videos keep extension listeners; no extension is also safe', () => {
  const f = fixture(); f.extension(); f.install(); f.burst(f.outside);
  assert.ok(f.errors.includes('limited'));
  assert.equal(f.outside.VideoTogetherDisabled, undefined);
  const absent = fixture(); absent.install(); absent.burst(absent.videos[0]);
  assert.deepEqual(absent.errors, []); assert.equal(absent.frameworkEvents(), 60);
});
