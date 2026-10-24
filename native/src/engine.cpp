#include "engine.h"

#include <algorithm>
#include <chrono>
#include <cmath>

namespace ddm {
namespace {
constexpr double gap = 24;
std::size_t image_bytes(const PreparedComment& comment) {
    return comment.image ? comment.image->pixels.size() : 0;
}
double speed_for(const ViewScene& view, double width) {
    return (view.width + width) / 8.0 * std::max(0.0, view.speed);
}
}

double monotonic_seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

Engine::View* Engine::find_view(std::uint64_t id) {
    auto it = std::find_if(views_.begin(), views_.end(), [id](const View& v) { return v.scene.view_id == id; });
    return it == views_.end() ? nullptr : &*it;
}
const Engine::View* Engine::find_view(std::uint64_t id) const {
    auto it = std::find_if(views_.begin(), views_.end(), [id](const View& v) { return v.scene.view_id == id; });
    return it == views_.end() ? nullptr : &*it;
}
bool Engine::running(const View& view) const {
    return scene_.visible && scene_.width > 0 && scene_.height > 0 && view.scene.visible &&
        !view.scene.paused && view.scene.width > 0 && view.scene.height > 0;
}
bool Engine::valid(const PreparedComment& comment) const {
    const auto* view = find_view(comment.view_id);
    return view && comment.room_epoch == view->scene.room_epoch && comment.style_rev == view->scene.style_rev;
}
std::size_t Engine::bytes() const {
    std::size_t result = 0;
    for (const auto& view : views_) for (const auto& item : view.active) result += image_bytes(item.comment);
    for (const auto& item : pending_) result += image_bytes(item.comment);
    return result;
}
bool Engine::lane_available(int lane, double speed, double x,
                            const std::vector<Active>& others) const {
    for (const auto& other : others) {
        if (other.lane != lane) continue;
        const double right = other.x + other.comment.width;
        const double distance = x - right;
        if (distance < gap) return false;
        if (speed > other.speed && other.speed > 0 &&
            (distance - gap) / (speed - other.speed) < right / other.speed) return false;
    }
    return true;
}
void Engine::prune(View& view) {
    std::vector<Active> kept;
    for (auto& item : view.active) {
        if (item.lane < view.scene.lanes && lane_available(item.lane, item.speed, item.x, kept))
            kept.push_back(std::move(item));
        else ++counters_.dropped_lanes;
    }
    view.active = std::move(kept);
}
void Engine::advance(double now) {
    if (!std::isfinite(now)) return;
    const double elapsed = clock_started_ ? std::max(0.0, now - last_now_) : 0;
    last_now_ = clock_started_ ? std::max(last_now_, now) : now;
    clock_started_ = true;
    for (auto& view : views_) {
        if (!running(view) || elapsed == 0) continue;
        for (auto& item : view.active) { item.x -= elapsed * item.speed; dirty_ = true; }
        view.active.erase(std::remove_if(view.active.begin(), view.active.end(), [](const Active& item) {
            return item.x + item.comment.width <= 0;
        }), view.active.end());
    }
}
void Engine::update_scene(const Scene& scene, double now) {
    advance(now);
    std::vector<View> next;
    for (const auto& spec : scene.views) {
        if (std::any_of(next.begin(), next.end(), [&](const View& v) { return v.scene.view_id == spec.view_id; })) continue;
        View view;
        auto* old = find_view(spec.view_id);
        if (old && old->scene.room_epoch == spec.room_epoch) {
            view = std::move(*old);
            for (auto& item : view.active) {
                const double progress = (view.scene.width - item.x) / std::max(1.0, view.scene.width + item.comment.width);
                item.x = spec.width - progress * (spec.width + item.comment.width);
                item.speed = speed_for(spec, item.comment.width);
            }
        }
        view.scene = spec;
        prune(view);
        next.push_back(std::move(view));
    }
    views_ = std::move(next);
    scene_ = scene;
    for (auto it = pending_.begin(); it != pending_.end();) {
        if (valid(it->comment)) { ++it; continue; }
        ++counters_.dropped_stale;
        it = pending_.erase(it);
    }
    dirty_ = true;
}
bool Engine::submit(PreparedComment comment, double now) {
    ++counters_.offered;
    processed_sequence_ = std::max(processed_sequence_, comment.sequence);
    auto* view = find_view(comment.view_id);
    if (!valid(comment) || !std::isfinite(now) || !std::isfinite(comment.age_seconds) ||
        !std::isfinite(comment.width) || !std::isfinite(comment.height) || comment.width <= 0 || comment.height <= 0 ||
        !comment.image || image_bytes(comment) == 0 || image_bytes(comment) > max_image_bytes) {
        ++counters_.dropped_stale;
        return false;
    }
    if (comment.replace) {
        if (std::none_of(view->active.begin(), view->active.end(), [&](const Active& item) {
            return item.comment.comment_id == comment.comment_id;
        })) { ++counters_.dropped_stale; return false; }
    } else {
        if ((comment.sequence && comment.sequence <= view->newest_sequence) ||
            std::any_of(view->active.begin(), view->active.end(), [&](const Active& item) { return item.comment.comment_id == comment.comment_id; }) ||
            std::any_of(pending_.begin(), pending_.end(), [&](const Pending& item) {
                return item.comment.view_id == comment.view_id && item.comment.comment_id == comment.comment_id;
            })) { ++counters_.dropped_stale; return false; }
        view->newest_sequence = std::max(view->newest_sequence, comment.sequence);
    }
    const double start = comment.submitted_at > 0 && comment.submitted_at <= now ? comment.submitted_at : now;
    const double deadline = start + comment_ttl - std::max(0.0, comment.age_seconds);
    if (!comment.replace && now >= deadline) { ++counters_.dropped_ttl; return false; }
    const auto count = std::count_if(pending_.begin(), pending_.end(), [&](const Pending& item) { return item.comment.view_id == comment.view_id; });
    if (pending_.size() >= max_pending || count >= max_pending_per_view) { ++counters_.dropped_queue; return false; }
    if (image_bytes(comment) > image_budget - std::min(image_budget, bytes())) { ++counters_.dropped_budget; return false; }
    pending_.push_back({std::move(comment), deadline});
    ++counters_.queued;
    return true;
}
std::size_t Engine::process_pending(double now, const std::function<bool(const PreparedComment&)>& upload) {
    advance(now);
    const double started = monotonic_seconds();
    std::size_t uploaded = 0, uploaded_bytes = 0;
    while (!pending_.empty()) {
        auto& pending = pending_.front();
        auto& comment = pending.comment;
        auto* view = find_view(comment.view_id);
        if (!valid(comment)) { ++counters_.dropped_stale; pending_.pop_front(); continue; }
        if (!comment.replace && now + monotonic_seconds() - started >= pending.deadline) {
            ++counters_.dropped_ttl; pending_.pop_front(); continue;
        }
        auto existing = std::find_if(view->active.begin(), view->active.end(), [&](const Active& item) { return item.comment.comment_id == comment.comment_id; });
        if (comment.replace && existing == view->active.end()) { ++counters_.dropped_stale; pending_.pop_front(); continue; }
        int lane = -1;
        const double speed = speed_for(view->scene, comment.width);
        if (!comment.replace) {
            if (running(*view) && view->active.size() < 80) {
                for (int i = 0; i < view->scene.lanes; ++i) {
                    if (lane_available(i, speed, view->scene.width, view->active)) { lane = i; break; }
                }
            }
            if (lane < 0) { ++counters_.dropped_lanes; pending_.pop_front(); continue; }
        }
        const auto size = image_bytes(comment);
        if (uploaded >= 8 || (uploaded && (uploaded_bytes + size > 4u * 1024u * 1024u || monotonic_seconds() - started >= .002))) break;
        if (!upload(comment)) break;
        ++uploaded;
        uploaded_bytes += size;
        if (!comment.replace && now + monotonic_seconds() - started >= pending.deadline) {
            ++counters_.dropped_ttl; pending_.pop_front(); continue;
        }
        if (comment.replace) {
            const double progress = (view->scene.width - existing->x) / std::max(1.0, view->scene.width + existing->comment.width);
            existing->x = view->scene.width - progress * (view->scene.width + comment.width);
            existing->speed = speed;
            existing->comment = std::move(comment);
            ++counters_.replaced;
            prune(*view);
        } else {
            view->active.push_back({std::move(comment), view->scene.width, speed, lane});
            ++counters_.admitted;
        }
        pending_.pop_front();
        dirty_ = true;
    }
    return uploaded;
}
std::vector<RenderItem> Engine::items() const {
    std::vector<RenderItem> result;
    for (const auto& view : views_) for (const auto& item : view.active)
        result.push_back({view.scene.view_id, item.comment.comment_id, item.x,
            item.lane * view.scene.lane_height, item.comment.width, item.comment.height, item.comment.image});
    return result;
}
EngineStatus Engine::status() const {
    EngineStatus result;
    result.processed_sequence = processed_sequence_;
    result.image_bytes = bytes();
    result.counters = counters_;
    for (const auto& view : views_) for (const auto& item : view.active)
        result.active.push_back({view.scene.view_id, item.comment.comment_id});
    for (const auto& item : pending_) result.pending.push_back({item.comment.view_id, item.comment.comment_id});
    return result;
}
bool Engine::moving() const {
    for (const auto& view : views_) if (running(view))
        for (const auto& item : view.active) if (item.speed > 0) return true;
    return false;
}
bool Engine::empty() const {
    for (const auto& view : views_) if (!view.active.empty()) return false;
    return true;
}
void Engine::clear() {
    for (auto& view : views_) view.active.clear();
    pending_.clear();
    dirty_ = true;
}

}
