#pragma once
#include "contract.h"
#include <memory>
#include <utility>

namespace ddm {
enum class HostState { Starting, Running, Suspended, Failed, Stopped };
struct HostStatus {
    HostState state = HostState::Starting;
    EngineStatus engine;
    std::uint64_t frames = 0, swap_chain_address = 0;
    std::size_t gpu_bytes = 0;
    std::size_t cpu_image_bytes = 0;
    std::string error_stage;
    std::int64_t error_hresult = 0;
    std::uint64_t error_sequence = 0;
    bool needs_visible = false;
};
class Host {
public:
    Host();
    ~Host();
    Host(const Host&) = delete;
    Host& operator=(const Host&) = delete;
    void attach(std::uintptr_t hwnd);
    void update_scene(Scene scene);
    std::pair<std::size_t, std::uint64_t> submit_batch(std::vector<PreparedComment> batch);
    HostStatus status_snapshot() const;
    DisplayStatistics display_statistics(std::uint64_t after_sequence = 0, std::size_t max_records = 8192) const;
    void request_close();
    bool reap();
private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};
}
