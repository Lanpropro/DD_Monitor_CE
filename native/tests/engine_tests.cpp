#include "engine.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool condition, const char* description) {
    if (!condition) throw std::runtime_error(description);
}
void close(double actual, double expected, const char* description) {
    check(std::abs(actual - expected) < 0.000001, description);
}
ddm::Scene scene(int lanes = 1) {
    ddm::Scene result;
    result.width = 1000;
    result.height = 400;
    ddm::ViewScene view;
    view.view_id = 1;
    view.room_epoch = 1;
    view.style_rev = 1;
    view.width = 1000;
    view.height = 400;
    view.lanes = lanes;
    view.lane_height = 40;
    result.views.push_back(view);
    return result;
}
ddm::PreparedComment comment(std::uint64_t id, double width = 100, std::size_t bytes = 400) {
    ddm::PreparedComment result;
    result.view_id = result.room_epoch = result.style_rev = 1;
    result.comment_id = result.sequence = id;
    result.width = width;
    result.height = 20;
    auto image = std::make_shared<ddm::Image>();
    image->width = 5;
    image->height = 20;
    image->stride = 20;
    image->pixels.resize(bytes);
    result.image = image;
    return result;
}
bool upload(const ddm::PreparedComment&) { return true; }
void admit(ddm::Engine& engine, ddm::PreparedComment item, double now) {
    check(engine.submit(std::move(item), now), "submission accepted");
    check(engine.process_pending(now, upload) == 1, "upload succeeds");
}
void motion_and_pause() {
    ddm::Engine engine;
    auto spec = scene();
    engine.update_scene(spec, 0);
    admit(engine, comment(1), 0);
    engine.mark_clean();
    check(!engine.dirty() && engine.moving(), "dirty cleared, movement remains");
    engine.advance(2);
    close(engine.items()[0].x, 725, "missed frames advance by elapsed wall time");
    spec.views[0].paused = true;
    engine.update_scene(spec, 2);
    engine.advance(20);
    close(engine.items()[0].x, 725, "paused position freezes");
    check(!engine.moving(), "paused engine has no motion");
    spec.views[0].speed = 2;
    engine.update_scene(spec, 20);
    close(engine.items()[0].x, 725, "speed change preserves position");
    spec.views[0].paused = false;
    engine.update_scene(spec, 22);
    engine.advance(23);
    close(engine.items()[0].x, 450, "resume uses changed speed without pause elapsed");
    spec.visible = false;
    engine.update_scene(spec, 23);
    engine.advance(100);
    close(engine.items()[0].x, 450, "hidden wall freezes");
    spec.visible = true;
    spec.width = 0;
    engine.update_scene(spec, 100);
    engine.advance(200);
    close(engine.items()[0].x, 450, "zero size freezes");
    spec.width = 1000;
    engine.update_scene(spec, 200);
    engine.advance(210);
    check(engine.empty() && engine.status().image_bytes == 0, "expiry reclaims image ledger");
}
void collision_and_resize() {
    ddm::Engine engine;
    auto spec = scene();
    engine.update_scene(spec, 0);
    admit(engine, comment(1), 0);
    engine.advance(.1);
    check(engine.submit(comment(2, 900), 1), "long follower queues");
    engine.process_pending(1, upload);
    check(engine.status().counters.dropped_lanes == 1 && engine.items().size() == 1,
          "fast long follower cannot catch short leader");
    admit(engine, comment(3, 50), 1);
    check(engine.items().size() == 2, "short slower follower admitted");
    spec.views[0].width = 500;
    engine.update_scene(spec, 2);
    close(engine.items()[0].x, 350, "resize keeps normalized progress");
    engine.advance(3);
    close(engine.items()[0].x, 275, "resize recalculates velocity");
    spec.views[0].lanes = 0;
    engine.update_scene(spec, 3);
    check(engine.empty(), "removed lanes prune comments");
}
void lane_preflight_is_conservative() {
    ddm::Engine engine;
    auto spec = scene();
    engine.update_scene(spec, 0);
    check(engine.status().views.size() == 1 && engine.status().views[0].can_start,
          "empty lane can start");
    admit(engine, comment(1), 0);
    auto status = engine.status();
    check(!status.views[0].can_start && status.active.size() == 1 &&
          status.pending.empty() && status.counters.offered == 1 &&
          status.counters.queued == 1 && status.counters.admitted == 1,
          "full lane preflight is reject-only");
    engine.advance(.1);
    check(!engine.status().views[0].can_start, "short elapsed time stays blocked");
    engine.advance(5);
    check(engine.status().views[0].can_start, "released lane can start");
    check(engine.submit(comment(2, 500), 5) && engine.process_pending(5, upload) == 1,
          "preflight true does not reserve or bypass final collision");
    check(!engine.status().views[0].can_start, "long speed-zero preflight remains conservative");
    spec.views[0].paused = true;
    engine.update_scene(spec, 8);
    check(!engine.status().views[0].can_start, "paused view cannot start");
    spec.views[0].paused = false;
    spec.views[0].lanes = 2;
    engine.update_scene(spec, 8);
    check(engine.status().views[0].can_start, "extra lane appears in native status");
    spec.views[0].room_epoch = 2;
    engine.update_scene(spec, 8);
    status = engine.status();
    check(status.views[0].room_epoch == 2 && status.views[0].style_rev == 1,
          "preflight carries generation identity");
    spec.views.clear();
    engine.update_scene(spec, 8);
    check(engine.status().views.empty(), "removed view disappears from preflight");
}
void generations_and_replacement() {
    ddm::Engine engine;
    auto spec = scene(3);
    engine.update_scene(spec, 0);
    admit(engine, comment(1), 0);
    engine.advance(2);
    spec.views[0].style_rev = 2;
    engine.update_scene(spec, 2);
    check(engine.items().size() == 1, "style retains old active texture");
    check(!engine.submit(comment(2), 2), "stale style rejected");
    auto replacement = comment(1, 300, 800);
    replacement.style_rev = 2;
    replacement.sequence = 3;
    replacement.replace = true;
    replacement.age_seconds = 99;
    admit(engine, replacement, 2);
    close(engine.items()[0].x, 675, "replacement changes width at same progress");
    check(engine.status().counters.admitted == 1 && engine.status().counters.replaced == 1,
          "replacement does not reenter");
    check(engine.status().image_bytes == 800, "replacement releases old image ledger");
    spec.views[0].room_epoch = 2;
    engine.update_scene(spec, 3);
    check(engine.empty() && engine.status().image_bytes == 0, "clear epoch empties active");
    check(!engine.submit(replacement, 3), "old epoch results rejected");
    auto item = comment(4);
    item.room_epoch = item.style_rev = 2;
    check(engine.submit(item, 3), "new epoch queued");
    spec.views.clear();
    engine.update_scene(spec, 3);
    check(!engine.pending_work() && engine.status().image_bytes == 0, "removed view frees pending bytes");
    check(!engine.submit(item, 3), "removed view rejects work");
}
void queue_and_upload() {
    ddm::Engine engine;
    engine.update_scene(scene(100), 0);
    for (unsigned i = 1; i <= 64; ++i) check(engine.submit(comment(i), 0), "bounded queue accepts capacity");
    check(!engine.submit(comment(65), 0), "per view queue cap");
    check(engine.status().pending.size() == 64 && engine.status().image_bytes == 64 * 400, "queued bytes tracked");
    check(engine.process_pending(0, [](const ddm::PreparedComment&) { return false; }) == 0,
          "upload failure does not admit");
    check(engine.empty() && engine.status().pending.size() == 64, "failed upload preserves pending");
    check(engine.process_pending(0, upload) == 8, "per frame image count bound");
    engine.process_pending(.5, upload);
    check(!engine.pending_work() && engine.status().counters.dropped_ttl == 56, "upload waiting counts toward TTL");
    check(engine.status().processed_sequence == 65, "rejected submissions acknowledged");
    engine.clear();
    check(engine.status().image_bytes == 0, "clear frees all bytes");
    auto old = comment(100);
    old.age_seconds = .5;
    check(!engine.submit(old, 1), "preparation age counts toward TTL");
    old.age_seconds = .2;
    old.sequence = old.comment_id = 101;
    old.submitted_at = 1;
    check(!engine.submit(old, 1.4), "host queue age counts toward TTL");
    check(engine.status().counters.dropped_ttl == 58, "both TTL origins accounted");
    auto large = comment(102, 100, 5u * 1024u * 1024u);
    admit(engine, large, 2);
    check(engine.items().size() == 1, "legal image larger than per frame byte budget progresses");
    engine.clear();
    for (unsigned i = 103; i < 111; ++i) check(engine.submit(comment(i, 100, ddm::max_image_bytes), 3), "CPU budget allows limit");
    check(!engine.submit(comment(111), 3), "CPU byte cap enforced");
    check(engine.status().image_bytes == ddm::image_budget, "CPU budget counts full image storage");
}
void replacement_collision_and_upload_limits() {
    ddm::Engine engine;
    auto spec = scene(100);
    engine.update_scene(spec, 0);
    check(engine.submit(comment(1, 100, 3u * 1024u * 1024u), 0), "first image queued");
    check(engine.submit(comment(2, 100, 3u * 1024u * 1024u), 0), "second image queued");
    check(engine.process_pending(0, upload) == 1 && engine.status().pending.size() == 1,
          "per frame upload byte limit");
    engine.process_pending(0, upload);
    for (unsigned id = 3; id <= 80; ++id) {
        check(engine.submit(comment(id), 0), "active cap preparation queued");
        engine.process_pending(0, upload);
    }
    check(engine.items().size() == 80, "eighty active comments allowed");
    check(engine.submit(comment(81), 0), "over active cap queued");
    check(engine.process_pending(0, upload) == 0 && engine.items().size() == 80,
          "active cap rejects before uploading");
    engine.clear();
    spec.views[0].lanes = 1;
    engine.update_scene(spec, 1);
    admit(engine, comment(82), 1);
    admit(engine, comment(83, 50), 3);
    auto replacement = comment(83, 2000);
    replacement.replace = true;
    replacement.sequence = 84;
    admit(engine, replacement, 3);
    check(engine.items().size() == 1 && engine.items()[0].comment_id == 82,
          "replacement width rechecks catch-up collision");
    auto pending = comment(85);
    check(engine.submit(pending, 3), "pending before style update");
    ++spec.views[0].style_rev;
    engine.update_scene(spec, 3);
    check(!engine.pending_work() && engine.items().size() == 1, "style invalidates pending while preserving active");
    pending.style_rev = spec.views[0].style_rev;
    pending.sequence = pending.comment_id = 86;
    check(engine.submit(pending, 3), "pending for exception test");
    bool propagated = false;
    try {
        engine.process_pending(3, [](const ddm::PreparedComment&) -> bool { throw std::runtime_error("device failed"); });
    } catch (const std::runtime_error&) { propagated = true; }
    check(propagated && engine.pending_work(), "device failure propagates without false admission");
}
void order_and_global_bound() {
    ddm::Engine engine;
    auto spec = scene(100);
    for (unsigned id = 2; id <= 5; ++id) {
        auto view = spec.views[0];
        view.view_id = id;
        spec.views.push_back(view);
    }
    engine.update_scene(spec, 0);
    for (unsigned id = 1; id <= 256; ++id) {
        auto item = comment(id);
        item.view_id = (id - 1) / 64 + 1;
        check(engine.submit(item, 0), "global queue accepts capacity");
    }
    auto overflow = comment(257);
    overflow.view_id = 5;
    check(!engine.submit(overflow, 0), "global queue cap enforced");
    engine.clear();
    auto newer = comment(300);
    admit(engine, newer, 1);
    check(!engine.submit(comment(299), 1), "older prepared result cannot reorder new messages");
    auto other = comment(301);
    other.view_id = 2;
    admit(engine, other, 1);
    std::swap(spec.views[0], spec.views[1]);
    engine.update_scene(spec, 1);
    check(engine.items()[0].view_id == 2 && engine.items()[1].view_id == 1, "scene order retained with stable view IDs");
    spec.views[0].mask = std::make_shared<ddm::Image>();
    engine.update_scene(spec, 1);
    check(engine.status().image_bytes == 800, "mask excluded from comment budget");
}
void display_buffer_limits() {
    ddm::DisplaySampleBuffer buffer;
    check(buffer.read(0,8192).samples.empty(), "empty display buffer");
    for (std::size_t i=0;i<ddm::display_sample_capacity+5;++i) {
        ddm::DisplaySample sample; sample.present_count=static_cast<std::uint32_t>(i);
        sample.hresult=0x887A000B; sample.moving=i%2==0;
        buffer.append(sample);
    }
    const auto first=buffer.read(0,3);
    check(first.samples.size()==3 && first.lost_count==5, "display ring overflow is bounded and reported");
    check(first.samples.front().record_sequence==6 && first.samples.back().record_sequence==8, "display cursor preserves ordered records");
    check(first.latest_sequence==ddm::display_sample_capacity+5, "display latest includes unreturned pages");
    check(first.samples[0].hresult==0x887A000B && !first.samples[0].moving, "display error and motion preserved");
    const auto next=buffer.read(8,2);
    check(next.lost_count==0 && next.samples.front().record_sequence==9, "display pagination resumes without loss");
    const auto all=buffer.read(0,ddm::display_sample_capacity+100);
    check(all.samples.size()==ddm::display_sample_capacity, "display oversized reads capped");
    check(buffer.read(0,0).samples.empty(), "display zero-size page");
    check(buffer.read(all.latest_sequence,8192).samples.empty(), "display final cursor empty");
    check(buffer.read(all.latest_sequence+1,8192).lost_count==0, "display future cursor does not underflow");
}

}

int main() {
    try {
        display_buffer_limits();
        motion_and_pause();
        collision_and_resize();
        lane_preflight_is_conservative();
        generations_and_replacement();
        queue_and_upload();
        order_and_global_bound();
        replacement_collision_and_upload_limits();
        std::cout << "engine tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
