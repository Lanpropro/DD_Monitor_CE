#include "host.h"
#include "engine.h"
#include "renderer.h"
#include <windows.h>
#include <algorithm>
#include <deque>
#include <cmath>
#include <mutex>
#include <thread>
#include <unordered_map>

namespace ddm {
struct Host::Impl {
    mutable std::mutex mutex;
    HostStatus status;
    DisplaySampleBuffer display_samples;
    std::uint64_t display_hwnd = 0, display_swap = 0;
    std::int64_t qpc_frequency = 0;
    void record_display(DisplaySample sample) {
        std::lock_guard<std::mutex> lock(mutex);
        display_hwnd = sample.hwnd; display_swap = sample.swap_chain_address;
        display_samples.append(std::move(sample));
    }
    Scene scene;
    std::deque<PreparedComment> queue;
    std::size_t queue_bytes = 0, inflight_bytes = 0, inflight_count = 0;
    bool scene_changed = false, closing = false, attached = false, exited = false;
    std::uint64_t sequence = 0, rejected = 0;
    HANDLE control = CreateEventW(nullptr,FALSE,FALSE,nullptr);
    HANDLE stop = CreateEventW(nullptr,TRUE,FALSE,nullptr);
    std::thread worker;
    ~Impl() { if (control) CloseHandle(control); if (stop) CloseHandle(stop); }
    static std::mutex& registry_mutex() { static auto* value = new std::mutex; return *value; }
    static std::vector<std::shared_ptr<Impl>>& registry() { static auto* value = new std::vector<std::shared_ptr<Impl>>; return *value; }
    void run(std::uintptr_t hwnd) noexcept;
};
Host::Host() : impl_(std::make_shared<Impl>()) {
    LARGE_INTEGER frequency{}; QueryPerformanceFrequency(&frequency); impl_->qpc_frequency = frequency.QuadPart;
    if (!impl_->control || !impl_->stop) throw std::runtime_error("CreateEvent failed");
}
Host::~Host() { request_close(); reap(); }
void Host::attach(std::uintptr_t hwnd) {
    auto p = impl_;
    std::lock_guard<std::mutex> lock(p->mutex);
    if (p->attached || p->closing) throw std::runtime_error("Host attach is attempt-once");
    if (!IsWindow(reinterpret_cast<HWND>(hwnd))) throw std::invalid_argument("Invalid host HWND");
    p->attached = true;
    { std::lock_guard<std::mutex> registry_lock(Impl::registry_mutex()); Impl::registry().push_back(p); }
    try { p->worker = std::thread([p,hwnd] { p->run(hwnd); }); }
    catch (...) {
        p->status.state = HostState::Failed; p->status.error_stage = "thread creation"; p->exited = true;
        throw;
    }
}
void Host::update_scene(Scene scene) {
    auto& p = *impl_; std::lock_guard<std::mutex> lock(p.mutex);
    if (p.closing || p.exited) return;
    p.scene = std::move(scene); p.scene_changed = true; SetEvent(p.control);
}
std::pair<std::size_t,std::uint64_t> Host::submit_batch(std::vector<PreparedComment> batch) {
    auto& p = *impl_; std::lock_guard<std::mutex> lock(p.mutex);
    if (p.closing || p.exited) return {0,p.sequence};
    const double now = monotonic_seconds();
    std::size_t queued = 0;
    std::unordered_map<std::uint64_t,std::size_t> per_view;
    for (const auto& item : p.queue) ++per_view[item.view_id];
    for (const auto& item : p.status.engine.pending) ++per_view[item.view_id];
    for (auto& item : batch) {
        const auto bytes = item.image ? item.image->pixels.size() : 0;
        if (!item.image || bytes > max_image_bytes || p.queue.size() + p.inflight_count + p.status.engine.pending.size() >= max_pending || per_view[item.view_id] >= max_pending_per_view || p.inflight_bytes > image_budget-p.queue_bytes || p.status.engine.image_bytes > image_budget-p.queue_bytes-p.inflight_bytes || bytes > image_budget-p.queue_bytes-p.inflight_bytes-p.status.engine.image_bytes) {
            ++p.rejected; ++p.status.engine.counters.offered; ++p.status.engine.counters.dropped_queue; continue;
        }
        item.sequence = ++p.sequence;
        if (!std::isfinite(item.submitted_at) || item.submitted_at <= 0 || item.submitted_at > now) item.submitted_at = now;
        p.queue_bytes += bytes; ++per_view[item.view_id]; p.queue.push_back(std::move(item)); ++queued;
    }
    SetEvent(p.control); return {queued,p.sequence};
}
HostStatus Host::status_snapshot() const {
    auto& p = *impl_; std::lock_guard<std::mutex> lock(p.mutex);
    auto result = p.status;
    result.cpu_image_bytes = result.engine.image_bytes + p.queue_bytes + p.inflight_bytes;
    return result;
}
DisplayStatistics Host::display_statistics(std::uint64_t after_sequence, std::size_t max_records) const {
    auto& p = *impl_; std::lock_guard<std::mutex> lock(p.mutex);
    auto result = p.display_samples.read(after_sequence,max_records);
    result.qpc_frequency = p.qpc_frequency;
    result.hwnd = p.display_hwnd; result.swap_chain_address = p.display_swap;
    return result;
}

void Host::request_close() {
    auto& p = *impl_; std::lock_guard<std::mutex> lock(p.mutex);
    p.closing = true; p.queue.clear(); p.queue_bytes = 0;
    if (!p.attached) { p.exited = true; p.status.state = HostState::Stopped; }
    SetEvent(p.stop); SetEvent(p.control);
}
bool Host::reap() {
    auto p = impl_;
    { std::lock_guard<std::mutex> lock(p->mutex); if (!p->exited) return false; }
    if (p->worker.joinable()) p->worker.join();
    std::lock_guard<std::mutex> lock(Impl::registry_mutex());
    auto& registry = Impl::registry(); registry.erase(std::remove(registry.begin(),registry.end(),p),registry.end()); return true;
}
void Host::Impl::run(std::uintptr_t hwnd) noexcept {
    Engine engine;
    Scene current;
    std::uint64_t host_rejected = 0;
    try {
        Renderer renderer;
        bool initialized = false, dirty = true, transparent = false, frame_ready = false, first_frame = true;
        for (;;) {
            std::deque<PreparedComment> incoming;
            bool changed = false;
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (closing) break;
                if (scene_changed) { current = scene; changed = true; scene_changed = false; }
                incoming.swap(queue); inflight_bytes = queue_bytes; inflight_count = incoming.size(); queue_bytes = 0;
                host_rejected = rejected;
            }
            const auto now = monotonic_seconds();
            if (changed) { engine.update_scene(current,now); dirty = true; }
            for (auto& item : incoming) engine.submit(std::move(item),now);
            const bool suspended = !current.visible || current.width <= 0 || current.height <= 0;
            if (!suspended && !initialized) { renderer.attach(hwnd,current.width,current.height); initialized = true; }
            if (!suspended && changed) renderer.resize(current.width,current.height);
            if (initialized) renderer.trim(engine.items());
            {
                std::lock_guard<std::mutex> lock(mutex);
                status.state = suspended ? HostState::Suspended : HostState::Running;
                status.swap_chain_address = renderer.swap_chain_address();
                status.gpu_bytes = renderer.gpu_bytes();
                if (suspended) status.needs_visible = false;
                status.engine = engine.status(); inflight_bytes = 0; inflight_count = 0; status.engine.counters.offered += host_rejected;
                status.engine.counters.dropped_queue += host_rejected;
            }
            const bool work = !suspended && (dirty || engine.dirty() || engine.moving() || engine.pending_work());
            if (!work || !frame_ready) {
                HANDLE handles[]{stop,control,work ? static_cast<HANDLE>(renderer.frame_handle()) : nullptr};
                const DWORD wait = WaitForMultipleObjects(work ? 3 : 2,handles,FALSE,INFINITE);
                if (wait == WAIT_OBJECT_0) break;
                if (wait == WAIT_OBJECT_0+1) continue;
                if (wait != WAIT_OBJECT_0+2) throw RenderError("WaitForMultipleObjects",HRESULT_FROM_WIN32(GetLastError()));
                frame_ready = true;
                record_display(renderer.display_sample(false));
            }
            if (WaitForSingleObject(stop,0) == WAIT_OBJECT_0) break;
            if (WaitForSingleObject(control,0) == WAIT_OBJECT_0) continue;
            const auto frame_now = monotonic_seconds();
            engine.advance(frame_now);
            renderer.trim(engine.items());
            engine.process_pending(frame_now,[&](const PreparedComment& item) { return renderer.prepare(item); });
            const auto items = engine.items();
            renderer.trim(items);
            if (WaitForSingleObject(stop,0) == WAIT_OBJECT_0) break;
            if (WaitForSingleObject(control,0) == WAIT_OBJECT_0) continue;
            if (!items.empty() || !transparent || dirty || engine.dirty()) {
                frame_ready = false; renderer.draw(current,items); transparent = items.empty();
                const auto kind = first_frame ? DisplayFrameKind::Initial : items.empty() ? DisplayFrameKind::Clear : DisplayFrameKind::Content;
                record_display(renderer.display_sample(true,engine.moving(),static_cast<std::uint32_t>(items.size()),kind));
                first_frame = false;
                std::lock_guard<std::mutex> lock(mutex); ++status.frames;
            }
            dirty = false; engine.mark_clean();
            {
                std::lock_guard<std::mutex> lock(mutex);
                status.engine = engine.status(); inflight_bytes = 0; inflight_count = 0; status.engine.counters.offered += host_rejected;
                status.engine.counters.dropped_queue += host_rejected;
                status.gpu_bytes = renderer.gpu_bytes(); status.needs_visible = !items.empty();
            }
        }
    } catch (const RenderError& error) {
        std::lock_guard<std::mutex> lock(mutex);
        status.state = HostState::Failed; status.error_stage = error.stage; status.error_hresult = error.code; ++status.error_sequence;
    } catch (const std::exception& error) {
        std::lock_guard<std::mutex> lock(mutex);
        status.state = HostState::Failed; status.error_stage = error.what(); status.error_hresult = E_FAIL; ++status.error_sequence;
    } catch (...) {
        std::lock_guard<std::mutex> lock(mutex);
        status.state = HostState::Failed; status.error_stage = "unknown render exception"; status.error_hresult = E_FAIL; ++status.error_sequence;
    }
    std::lock_guard<std::mutex> lock(mutex);
    if (status.state != HostState::Failed) status.state = HostState::Stopped;
    status.needs_visible = false; status.gpu_bytes = 0; closing = true; exited = true;
    status.swap_chain_address = 0;
    status.engine.active.clear(); status.engine.pending.clear(); status.engine.image_bytes = 0;
    queue.clear(); queue_bytes = 0; inflight_bytes = 0; inflight_count = 0;
}
}
