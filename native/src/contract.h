#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>
#include <deque>
#include <algorithm>
#include <utility>

namespace ddm {

constexpr std::size_t image_budget = 128u * 1024u * 1024u;
constexpr std::size_t max_image_bytes = 16u * 1024u * 1024u;
constexpr std::size_t max_pending = 256;
constexpr std::size_t max_pending_per_view = 64;
constexpr double comment_ttl = 0.5;

struct Image {
    int width = 0;
    int height = 0;
    int stride = 0;
    std::vector<std::uint8_t> pixels;
};

struct Rect {
    int x = 0, y = 0, width = 0, height = 0;
};

struct ViewScene {
    std::uint64_t view_id = 0, room_epoch = 0, style_rev = 0;
    double width = 0, height = 0, lane_height = 0;
    int lanes = 0;
    double speed = 1, opacity = 1;
    bool visible = true, paused = false;
    Rect clip;
    std::shared_ptr<const Image> mask;
};

struct Scene {
    std::uint64_t layout_rev = 0;
    int width = 0, height = 0;
    bool visible = true;
    std::string screen;
    std::vector<ViewScene> views;
};

struct PreparedComment {
    std::uint64_t view_id = 0, room_epoch = 0, style_rev = 0;
    std::uint64_t comment_id = 0, sequence = 0;
    bool replace = false;
    double width = 0, height = 0;
    double age_seconds = 0, submitted_at = 0;
    std::shared_ptr<const Image> image;
};

struct RenderItem {
    std::uint64_t view_id = 0, comment_id = 0;
    double x = 0, y = 0, width = 0, height = 0;
    std::shared_ptr<const Image> image;
};

struct CommentRef {
    std::uint64_t view_id = 0, comment_id = 0;
};

struct Counters {
    std::uint64_t offered = 0, queued = 0, admitted = 0, replaced = 0;
    std::uint64_t dropped_queue = 0, dropped_stale = 0, dropped_ttl = 0;
    std::uint64_t dropped_lanes = 0, dropped_budget = 0;
};

struct EngineStatus {
    std::uint64_t processed_sequence = 0;
    std::vector<CommentRef> active, pending;
    std::size_t image_bytes = 0;
    Counters counters;
};

constexpr std::size_t display_sample_capacity = 32768;
enum class DisplayFrameKind { Unknown, Initial, Content, Clear };
struct DisplaySample {
    std::uint64_t record_sequence = 0, swap_chain_address = 0, hwnd = 0;
    std::int64_t observed_qpc = 0, sync_qpc = 0;
    std::uint32_t hresult = 0, last_present_hresult = 0;
    std::uint32_t present_count = 0, present_refresh_count = 0, sync_refresh_count = 0;
    std::uint32_t last_present_count = 0, active_count = 0;
    bool after_present = false, moving = false;
    DisplayFrameKind frame_kind = DisplayFrameKind::Unknown;
};
struct DisplayStatistics {
    std::vector<DisplaySample> samples;
    std::uint64_t lost_count = 0, latest_sequence = 0, hwnd = 0, swap_chain_address = 0;
    std::int64_t qpc_frequency = 0;
};

class DisplaySampleBuffer {
public:
    void append(DisplaySample sample) {
        sample.record_sequence = ++sequence_;
        if (samples_.size() == display_sample_capacity) samples_.pop_front();
        samples_.push_back(std::move(sample));
    }
    DisplayStatistics read(std::uint64_t after_sequence, std::size_t max_records) const {
        DisplayStatistics result;
        result.latest_sequence = sequence_;
        if (!samples_.empty() && after_sequence < samples_.front().record_sequence - 1)
            result.lost_count = samples_.front().record_sequence - 1 - after_sequence;
        max_records = std::min(max_records,display_sample_capacity);
        result.samples.reserve(std::min(max_records,samples_.size()));
        for (const auto& sample : samples_) {
            if (sample.record_sequence <= after_sequence) continue;
            if (result.samples.size() == max_records) break;
            result.samples.push_back(sample);
        }
        return result;
    }
private:
    std::deque<DisplaySample> samples_;
    std::uint64_t sequence_ = 0;
};

double monotonic_seconds();

}
