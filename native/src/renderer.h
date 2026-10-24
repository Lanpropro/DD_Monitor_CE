#pragma once
#include "contract.h"
#include <memory>
#include <stdexcept>
#include <unordered_set>

namespace ddm {
struct RenderError : std::runtime_error {
    std::string stage;
    long code;
    RenderError(std::string stage, long code);
};
class Renderer {
public:
    Renderer();
    ~Renderer();
    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;
    void attach(std::uintptr_t hwnd, int width, int height);
    void resize(int width, int height);
    bool prepare(const PreparedComment& comment);
    void draw(const Scene& scene, const std::vector<RenderItem>& items);
    void* frame_handle() const;
    DisplaySample display_sample(bool after_present, bool moving = false, std::uint32_t active_count = 0,
                                 DisplayFrameKind kind = DisplayFrameKind::Unknown);
    void trim(const std::vector<RenderItem>& items);
    std::size_t gpu_bytes() const;
    std::uint64_t swap_chain_address() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
