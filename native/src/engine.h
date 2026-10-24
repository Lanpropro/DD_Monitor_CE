#pragma once

#include "contract.h"
#include <deque>
#include <functional>

namespace ddm {

class Engine {
public:
    void update_scene(const Scene& scene, double now);
    bool submit(PreparedComment comment, double now);
    void advance(double now);
    std::size_t process_pending(double now,
        const std::function<bool(const PreparedComment&)>& upload);
    std::vector<RenderItem> items() const;
    EngineStatus status() const;
    bool moving() const;
    bool dirty() const { return dirty_; }
    void mark_clean() { dirty_ = false; }
    bool empty() const;
    bool pending_work() const { return !pending_.empty(); }
    void clear();

private:
    struct Active {
        PreparedComment comment;
        double x = 0, speed = 0;
        int lane = 0;
    };
    struct View {
        ViewScene scene;
        std::vector<Active> active;
        std::uint64_t newest_sequence = 0;
    };
    struct Pending { PreparedComment comment; double deadline = 0; };
    View* find_view(std::uint64_t id);
    const View* find_view(std::uint64_t id) const;
    bool running(const View& view) const;
    bool valid(const PreparedComment& comment) const;
    bool lane_available(int lane, double speed, double x,
                        const std::vector<Active>& others) const;
    void prune(View& view);
    std::size_t bytes() const;
    Scene scene_;
    std::vector<View> views_;
    std::deque<Pending> pending_;
    Counters counters_;
    std::uint64_t processed_sequence_ = 0;
    double last_now_ = 0;
    bool clock_started_ = false, dirty_ = true;
};

}
