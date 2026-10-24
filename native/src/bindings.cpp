#include "host.h"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <unordered_set>

namespace py = pybind11;
using namespace ddm;

namespace {
template<class T> T value(const py::dict& source, const char* key, T fallback) {
    return source.contains(key) ? py::cast<T>(source[key]) : fallback;
}

double number(const py::dict& source, const char* key, double fallback,
              double minimum, double maximum) {
    const double result = value(source, key, fallback);
    if (!std::isfinite(result) || result < minimum || result > maximum)
        throw py::value_error(std::string("Invalid ") + key);
    return result;
}

std::shared_ptr<const Image> image_from(const py::dict& source, std::size_t limit) {
    if (value<std::string>(source, "format", "") != "BGRA_PREMULTIPLIED")
        throw py::value_error("Expected BGRA_PREMULTIPLIED image");
    const auto width = value<std::int64_t>(source, "width", 0);
    const auto height = value<std::int64_t>(source, "height", 0);
    const auto stride = value<std::int64_t>(source, "stride", 0);
    if (width <= 0 || height <= 0 || width > 16384 || height > 16384 ||
        stride < width * 4 || stride > static_cast<std::int64_t>(limit) ||
        height > static_cast<std::int64_t>(limit) / stride)
        throw py::value_error("Invalid image dimensions, stride or byte budget");
    const auto size = static_cast<std::size_t>(stride * height);
    auto buffer = py::cast<py::buffer>(source["pixels"]);
    auto info = buffer.request();
    if (info.ndim != 1 || info.itemsize != 1 || info.strides[0] != 1 ||
        info.size != static_cast<py::ssize_t>(size))
        throw py::value_error("Image pixels must be a contiguous byte buffer of stride * height");
    auto result = std::make_shared<Image>();
    result->width = static_cast<int>(width);
    result->height = static_cast<int>(height);
    result->stride = static_cast<int>(stride);
    result->pixels.resize(size);
    std::memcpy(result->pixels.data(), info.ptr, size);
    return result;
}

Scene scene_from(const py::dict& source) {
    Scene result;
    result.layout_rev = value<std::uint64_t>(source, "layout_rev", 0);
    result.width = static_cast<int>(number(source, "width", 0, 0, 16384));
    result.height = static_cast<int>(number(source, "height", 0, 0, 16384));
    result.visible = value(source, "visible", true);
    result.screen = value<std::string>(source, "screen", "");
    auto views = py::cast<py::list>(source["views"]);
    if (views.size() > 16) throw py::value_error("At most 16 views per scene");
    std::unordered_set<std::uint64_t> ids;
    std::size_t masks = 0;
    for (auto item : views) {
        auto data = py::cast<py::dict>(item);
        ViewScene view;
        view.view_id = py::cast<std::uint64_t>(data["view_id"]);
        if (view.view_id == 0 || !ids.insert(view.view_id).second)
            throw py::value_error("View IDs must be unique and nonzero");
        view.room_epoch = py::cast<std::uint64_t>(data["room_epoch"]);
        view.style_rev = py::cast<std::uint64_t>(data["style_rev"]);
        view.width = number(data, "width", 0, 0, 16384);
        view.height = number(data, "height", 0, 0, 16384);
        view.lane_height = number(data, "lane_height", 1, 1, 4096);
        view.lanes = static_cast<int>(number(data, "lanes", 0, 0, 256));
        view.speed = number(data, "speed", 1, 0.01, 20);
        view.opacity = number(data, "opacity", 1, 0, 1);
        view.visible = value(data, "visible", true);
        view.paused = value(data, "paused", false);
        auto clip = py::cast<py::dict>(data["clip"]);
        view.clip.x = static_cast<int>(number(clip, "x", 0, -32768, 32768));
        view.clip.y = static_cast<int>(number(clip, "y", 0, -32768, 32768));
        view.clip.width = static_cast<int>(number(clip, "width", 0, 0, 16384));
        view.clip.height = static_cast<int>(number(clip, "height", 0, 0, 16384));
        if (data.contains("mask") && !data["mask"].is_none()) {
            view.mask = image_from(py::cast<py::dict>(data["mask"]), image_budget);
            masks += view.mask->pixels.size();
            if (masks > image_budget) throw py::value_error("Scene mask budget exceeded");
        }
        result.views.push_back(std::move(view));
    }
    return result;
}

std::vector<PreparedComment> batch_from(const py::list& source) {
    if (source.size() > max_pending) throw py::value_error("Batch exceeds queue capacity");
    std::vector<PreparedComment> result;
    std::size_t bytes = 0;
    for (auto item : source) {
        auto data = py::cast<py::dict>(item);
        PreparedComment comment;
        comment.view_id = py::cast<std::uint64_t>(data["view_id"]);
        comment.room_epoch = py::cast<std::uint64_t>(data["room_epoch"]);
        comment.style_rev = py::cast<std::uint64_t>(data["style_rev"]);
        comment.comment_id = py::cast<std::uint64_t>(data["comment_id"]);
        if (!comment.view_id || !comment.comment_id) throw py::value_error("IDs must be nonzero");
        comment.replace = value(data, "replace", false);
        comment.width = number(data, "width", 0, 0.001, 16384);
        comment.height = number(data, "height", 0, 0.001, 16384);
        comment.age_seconds = number(data, "age_seconds", 0, 0, 86400);
        comment.submitted_at = monotonic_seconds();
        comment.image = image_from(py::cast<py::dict>(data["image"]), max_image_bytes);
        bytes += comment.image->pixels.size();
        if (bytes > image_budget) throw py::value_error("Batch byte budget exceeded");
        result.push_back(std::move(comment));
    }
    return result;
}

py::list refs(const std::vector<CommentRef>& source) {
    py::list result;
    for (const auto& item : source)
        result.append(py::make_tuple(item.view_id, item.comment_id));
    return result;
}

py::dict status_dict(const HostStatus& status) {
    const auto& counters = status.engine.counters;
    py::dict count;
#define COUNT(name) count[#name] = counters.name
    COUNT(offered); COUNT(queued); COUNT(admitted); COUNT(replaced);
    COUNT(dropped_queue); COUNT(dropped_stale); COUNT(dropped_ttl);
    COUNT(dropped_lanes); COUNT(dropped_budget);
#undef COUNT
    const char* state = "Starting";
    switch (status.state) {
    case HostState::Starting: break;
    case HostState::Running: state = "Running"; break;
    case HostState::Suspended: state = "Suspended"; break;
    case HostState::Failed: state = "Failed"; break;
    case HostState::Stopped: state = "Stopped"; break;
    }
    py::dict result;
    result["state"] = state;
    result["processed_sequence"] = status.engine.processed_sequence;
    result["active"] = refs(status.engine.active);
    result["pending"] = refs(status.engine.pending);
    result["image_bytes"] = status.engine.image_bytes;
    result["cpu_image_bytes"] = status.cpu_image_bytes;
    result["gpu_bytes"] = status.gpu_bytes;
    result["frames"] = status.frames;
    result["swap_chain_address"] = status.swap_chain_address;
    result["needs_visible"] = status.needs_visible;
    result["error_stage"] = status.error_stage;
    result["error_hresult"] = status.error_hresult;
    result["error_sequence"] = status.error_sequence;
    result["counters"] = count;
    return result;
}
py::dict display_dict(const DisplayStatistics& statistics) {
    py::list samples;
    for (const auto& sample : statistics.samples) {
        py::dict row;
#define DISPLAY_FIELD(name) row[#name] = sample.name
        DISPLAY_FIELD(record_sequence); DISPLAY_FIELD(observed_qpc); DISPLAY_FIELD(hresult);
        DISPLAY_FIELD(present_count); DISPLAY_FIELD(present_refresh_count); DISPLAY_FIELD(sync_refresh_count);
        DISPLAY_FIELD(sync_qpc); DISPLAY_FIELD(last_present_count); DISPLAY_FIELD(last_present_hresult);
        DISPLAY_FIELD(moving); DISPLAY_FIELD(active_count); DISPLAY_FIELD(swap_chain_address); DISPLAY_FIELD(hwnd);
#undef DISPLAY_FIELD
        row["phase"] = sample.after_present ? "present" : "permit";
        const char* kind = "unknown";
        switch (sample.frame_kind) {
        case DisplayFrameKind::Initial: kind = "initial"; break;
        case DisplayFrameKind::Content: kind = "content"; break;
        case DisplayFrameKind::Clear: kind = "clear"; break;
        case DisplayFrameKind::Unknown: break;
        }
        row["frame_kind"] = kind;
        samples.append(std::move(row));
    }
    py::dict result;
    result["samples"] = samples; result["lost_count"] = statistics.lost_count;
    result["latest_sequence"] = statistics.latest_sequence; result["qpc_frequency"] = statistics.qpc_frequency;
    result["capacity"] = display_sample_capacity; result["hwnd"] = statistics.hwnd;
    result["swap_chain_address"] = statistics.swap_chain_address;
    return result;
}

}

PYBIND11_MODULE(_native_danmaku, module) {
    module.attr("contract_version") = 1;
    py::class_<Host>(module, "NativeDanmakuHost")
        .def(py::init<>())
        .def("attach", &Host::attach, py::call_guard<py::gil_scoped_release>())
        .def("update_scene", [](Host& host, const py::dict& source) {
            auto scene = scene_from(source);
            py::gil_scoped_release release;
            host.update_scene(std::move(scene));
        })
        .def("submit_batch", [](Host& host, const py::list& source) {
            auto batch = batch_from(source);
            py::gil_scoped_release release;
            return host.submit_batch(std::move(batch));
        })
        .def("status_snapshot", [](const Host& host) { return status_dict(host.status_snapshot()); })
        .def("display_statistics", [](const Host& host, std::uint64_t after_sequence, std::size_t max_records) {
            DisplayStatistics statistics;
            { py::gil_scoped_release release; statistics = host.display_statistics(after_sequence,max_records); }
            return display_dict(statistics);
        }, py::arg("after_sequence") = 0, py::arg("max_records") = 8192)
        .def("request_close", &Host::request_close, py::call_guard<py::gil_scoped_release>())
        .def("reap", &Host::reap, py::call_guard<py::gil_scoped_release>());
}
