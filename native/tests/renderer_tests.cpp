#include "host.h"
#include "renderer.h"
#include <windows.h>
#include <chrono>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <atomic>

static void require(bool condition,const char* message) { if (!condition) throw std::runtime_error(message); }
static bool pump_until(const std::function<bool()>& predicate,int milliseconds=5000) {
    const auto deadline = std::chrono::steady_clock::now()+std::chrono::milliseconds(milliseconds);
    do {
        MSG message;
        while (PeekMessageW(&message,nullptr,0,0,PM_REMOVE)) { TranslateMessage(&message); DispatchMessageW(&message); }
        if (predicate()) return true;
        Sleep(2);
    } while (std::chrono::steady_clock::now()<deadline);
    return predicate();
}
static LRESULT CALLBACK window_proc(HWND hwnd,UINT message,WPARAM wparam,LPARAM lparam) {
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    return DefWindowProcW(hwnd,message,wparam,lparam);
}
static COLORREF desktop_pixel(int x,int y) {
    HDC dc=GetDC(nullptr); const auto color=GetPixel(dc,x,y); ReleaseDC(nullptr,dc); return color;
}
static bool close_color(COLORREF actual,COLORREF expected) {
    return std::abs(static_cast<int>(GetRValue(actual))-GetRValue(expected))<=4 &&
           std::abs(static_cast<int>(GetGValue(actual))-GetGValue(expected))<=4 &&
           std::abs(static_cast<int>(GetBValue(actual))-GetBValue(expected))<=4;
}
static void pixel_prototype(HWND window) {
    ddm::Renderer renderer; renderer.attach(reinterpret_cast<std::uintptr_t>(window),640,360);
    ddm::Scene scene; scene.width=640; scene.height=360;
    auto image=std::make_shared<ddm::Image>(); image->width=100; image->height=50; image->stride=400; image->pixels.resize(20000);
    for (std::size_t i=0;i<image->pixels.size();i+=4) { image->pixels[i]=0; image->pixels[i+1]=100; image->pixels[i+2]=128; image->pixels[i+3]=128; }
    ddm::PreparedComment prepared; prepared.image=image; require(renderer.prepare(prepared),"prototype upload");
    std::vector<ddm::RenderItem> items;
    for (int i=0;i<4;++i) {
        ddm::ViewScene view; view.view_id=i+1; view.width=320; view.height=180; view.clip={i%2*320,i/2*180,320,180};
        view.opacity=i==3 ? 0.5 : 1.0;
        auto mask=std::make_shared<ddm::Image>(); mask->width=320; mask->height=180; mask->stride=1280; mask->pixels.assign(1280*180,255);
        for (int y=20;y<40;++y) for (int x=40;x<60;++x) mask->pixels[y*1280+x*4+3]=0;
        view.mask=mask; scene.views.push_back(view);
        ddm::RenderItem item; item.view_id=i+1; item.comment_id=i+1; item.x=10; item.y=10; item.width=100; item.height=50; item.image=image;
        items.push_back(item);
    }
    require(pump_until([&] { return WaitForSingleObject(renderer.frame_handle(),0)==WAIT_OBJECT_0; }),"prototype frame permit");
    renderer.draw(scene,items); pump_until([] { return false; },200);
    for (int i=0;i<4;++i) {
        const int x=40+i%2*320,y=40+i/2*180;
        const auto blended=desktop_pixel(x+20,y+15), hole=desktop_pixel(x+50,y+30), outside=desktop_pixel(x+5,y+5);
        std::cout << "pixel view " << i << " blend=" << static_cast<int>(GetRValue(blended)) << "," << static_cast<int>(GetGValue(blended)) << "," << static_cast<int>(GetBValue(blended))
            << " outside=" << static_cast<int>(GetRValue(outside)) << "," << static_cast<int>(GetGValue(outside)) << "," << static_cast<int>(GetBValue(outside)) << " hole=" << static_cast<int>(GetRValue(hole)) << "," << static_cast<int>(GetGValue(hole)) << "," << static_cast<int>(GetBValue(hole)) << '\n';
        require(close_color(outside,RGB(20,40,180)),"transparent background pixel");
        require(close_color(hole,RGB(20,40,180)),"mask hole pixel");
        require(close_color(blended,i==3 ? RGB(79,80,135) : RGB(138,120,90)),"premultiplied opacity pixel");
    }
    items.resize(1); items[0].x=300;
    renderer.trim(scene,items);
    require(renderer.gpu_bytes()<8u*1024u*1024u,"trim releases textures and masks for inactive views");
    require(pump_until([&] { return WaitForSingleObject(renderer.frame_handle(),0)==WAIT_OBJECT_0; }),"clip frame permit");
    renderer.draw(scene,items); pump_until([] { return false; },100);
    require(close_color(desktop_pixel(40+310,40+15),RGB(138,120,90)),"clip inside pixel");
    require(close_color(desktop_pixel(40+350,40+15),RGB(20,40,180)),"per view scissor pixel");
    auto large_mask=std::make_shared<ddm::Image>();
    large_mask->width=3072; large_mask->height=1536; large_mask->stride=3072*4;
    large_mask->pixels.assign(static_cast<std::size_t>(large_mask->stride)*large_mask->height,255);
    for (auto& view : scene.views) view.mask=large_mask;
    items.clear();
    renderer.trim(scene,items);
    require(renderer.gpu_bytes()<4u*1024u*1024u,"empty items do not retain view masks");
    require(pump_until([&] { return WaitForSingleObject(renderer.frame_handle(),0)==WAIT_OBJECT_0; }),"large mask frame permit");
    renderer.draw(scene,{});
    require(renderer.gpu_bytes()<4u*1024u*1024u,"draw without items does not upload masks");
    for (auto& view : scene.views) view.view_id+=10;
    for (int i=0;i<4;++i) {
        ddm::RenderItem item; item.view_id=i+11; item.comment_id=i+1; item.x=10; item.y=10;
        item.width=100; item.height=50; item.image=large_mask; items.push_back(item);
    }
    require(pump_until([&] { return WaitForSingleObject(renderer.frame_handle(),0)==WAIT_OBJECT_0; }),"replacement mask frame permit");
    renderer.draw(scene,items);
    require(renderer.gpu_bytes()>=72u*1024u*1024u && renderer.gpu_bytes()<80u*1024u*1024u,
            "new view masks replace old budget before uploading");
    renderer.trim(scene,{});
    require(renderer.gpu_bytes()<4u*1024u*1024u,"mask trim releases inactive view resources");
    std::weak_ptr<const ddm::Image> retained_mask=large_mask;
    large_mask.reset(); for (auto& view : scene.views) view.mask.reset();
    items.clear();
    renderer.trim(scene,{});
    require(retained_mask.expired(),"mask trim releases its CPU image");
}
static void suspended_clear_releases_textures(HWND window) {
    ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window));
    ddm::Scene scene; scene.width=640; scene.height=360;
    ddm::ViewScene view; view.view_id=1; view.width=640; view.height=360;
    view.lane_height=40; view.lanes=1; view.clip={0,0,640,360};
    auto mask=std::make_shared<ddm::Image>();
    mask->width=640; mask->height=360; mask->stride=2560; mask->pixels.assign(2560*360,255);
    view.mask=std::move(mask);
    scene.views.push_back(view); host.update_scene(scene);
    auto image=std::make_shared<ddm::Image>();
    image->width=80; image->height=24; image->stride=320; image->pixels.assign(320*24,255);
    std::weak_ptr<const ddm::Image> retained=image;
    ddm::PreparedComment comment; comment.view_id=1; comment.comment_id=1;
    comment.width=80; comment.height=24; comment.image=std::move(image);
    require(host.submit_batch({std::move(comment)}).first==1,"suspended-clear submission");
    require(pump_until([&] {
        const auto status=host.status_snapshot();
        return status.engine.active.size()==1 && status.gpu_bytes>0;
    }),"suspended-clear image uploaded");
    scene.visible=false; host.update_scene(scene);
    require(pump_until([&] {
        const auto status=host.status_snapshot();
        return status.state==ddm::HostState::Suspended;
    }),"suspended host releases GPU resources");
    require(!retained.expired(),"suspended active texture retains CPU image");
    const auto frames=host.status_snapshot().frames;
    ++scene.views[0].room_epoch; host.update_scene(scene);
    require(pump_until([&] {
        const auto status=host.status_snapshot();
        return status.state==ddm::HostState::Suspended && status.engine.active.empty() &&
            status.cpu_image_bytes==0 && retained.expired();
    }),"suspended clear releases comment texture and CPU image without a frame");
    require(host.status_snapshot().frames==frames,"suspended clear does not present");
    std::cout << "PASS: suspended clear releases GPU texture and weak CPU image without presenting" << std::endl;
    host.request_close();
    require(pump_until([&] { return host.reap(); }),"suspended-clear host close");
}
static void hidden_suspend_releases_mask(HWND window) {
    ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window));
    ddm::Scene scene; scene.width=640; scene.height=360;
    ddm::ViewScene view; view.view_id=1; view.width=640; view.height=360;
    view.lane_height=40; view.lanes=1; view.clip={0,0,640,360};
    auto mask=std::make_shared<ddm::Image>();
    mask->width=640; mask->height=360; mask->stride=2560; mask->pixels.assign(2560*360,255);
    view.mask=mask; scene.views.push_back(view); host.update_scene(scene);
    auto image=std::make_shared<ddm::Image>();
    image->width=80; image->height=24; image->stride=320; image->pixels.assign(320*24,255);
    ddm::PreparedComment comment; comment.view_id=1; comment.comment_id=1;
    comment.width=80; comment.height=24; comment.image=std::move(image);
    require(host.submit_batch({std::move(comment)}).first==1,"hidden-mask submission");
    require(pump_until([&] { return host.status_snapshot().engine.active.size()==1; }),
            "hidden-mask active comment admitted");
    scene.visible=false; host.update_scene(scene);
    require(pump_until([&] {
        const auto status=host.status_snapshot();
        return status.state==ddm::HostState::Suspended && status.gpu_bytes<4u*1024u*1024u;
    }),"hidden host releases mask while retaining active comment texture");
    host.request_close(); require(pump_until([&] { return host.reap(); }),"hidden-mask host close");
}
static void paused_clear_releases_mask(HWND window) {
    ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window));
    ddm::Scene scene; scene.width=640; scene.height=360;
    ddm::ViewScene view; view.view_id=1; view.width=640; view.height=360;
    view.lane_height=40; view.lanes=1; view.clip={0,0,640,360};
    auto mask=std::make_shared<ddm::Image>();
    mask->width=640; mask->height=360; mask->stride=2560; mask->pixels.assign(2560*360,255);
    view.mask=mask; scene.views.push_back(view); host.update_scene(scene);
    auto image=std::make_shared<ddm::Image>();
    image->width=80; image->height=24; image->stride=320; image->pixels.assign(320*24,255);
    ddm::PreparedComment comment; comment.view_id=1; comment.comment_id=1;
    comment.width=80; comment.height=24; comment.image=std::move(image);
    require(host.submit_batch({std::move(comment)}).first==1,"paused-mask submission");
    require(pump_until([&] { return host.status_snapshot().engine.active.size()==1; }),"paused-mask admission");
    scene.views[0].paused=true; host.update_scene(scene);
    require(pump_until([&] { return host.status_snapshot().gpu_bytes>0; }),"paused active mask uploaded");
    ++scene.views[0].room_epoch; host.update_scene(scene);
    require(pump_until([&] {
        const auto status=host.status_snapshot();
        return status.engine.active.empty() && status.gpu_bytes==0;
    }),"paused clear releases mask without a content frame");
    host.request_close(); require(pump_until([&] { return host.reap(); }),"paused-mask host close");
}
static void destructor_and_concurrent_reap_join_once(HWND window) {
    {
        ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window));
        ddm::Scene scene; scene.width=640; scene.height=360;
        scene.views.push_back(ddm::ViewScene{}); scene.views[0].view_id=1;
        scene.views[0].width=640; scene.views[0].height=360; scene.views[0].lane_height=40; scene.views[0].lanes=2;
        scene.views[0].clip={0,0,640,360};
        host.update_scene(scene);
        require(pump_until([&] { return host.status_snapshot().frames>0; }),"destructor host started");
    }
    for (int iteration=1;iteration<=8;++iteration) {
        ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window)); host.request_close();
        require(pump_until([&] { return host.status_snapshot().state==ddm::HostState::Stopped; }),"concurrent reap host stopped");
        std::atomic<int> reaped{};
        std::thread first([&] { if (host.reap()) ++reaped; });
        std::thread second([&] { if (host.reap()) ++reaped; });
        first.join(); second.join();
        require(reaped.load()==1,"each host reaps exactly once");
    }
}
int main() {
    try {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        { ddm::Host host; host.request_close(); require(host.reap(),"unattached host closes"); }
        WNDCLASSW cls{}; cls.lpfnWndProc = window_proc; cls.hInstance = GetModuleHandleW(nullptr); cls.lpszClassName = L"DDMRendererTest"; cls.hbrBackground=CreateSolidBrush(RGB(20,40,180));
        require(RegisterClassW(&cls)!=0,"RegisterClass");
        HWND background=CreateWindowExW(WS_EX_TOPMOST|WS_EX_TOOLWINDOW,cls.lpszClassName,L"D3D background",WS_POPUP,40,40,640,360,nullptr,nullptr,cls.hInstance,nullptr);
        require(background!=nullptr,"background window"); ShowWindow(background,SW_SHOWNOACTIVATE); UpdateWindow(background);
        HWND window = CreateWindowExW(WS_EX_TOPMOST|WS_EX_LAYERED|WS_EX_NOREDIRECTIONBITMAP|WS_EX_NOACTIVATE|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW,
            cls.lpszClassName,L"D3D11 smoke (not display acceptance)",WS_POPUP,40,40,640,360,background,nullptr,cls.hInstance,nullptr);
        require(window!=nullptr,"CreateWindow");
        require(SetLayeredWindowAttributes(window,0,255,LWA_ALPHA)!=FALSE,"layered input passthrough");
        ShowWindow(window,SW_SHOWNOACTIVATE);
        pixel_prototype(window);
        suspended_clear_releases_textures(window);
        hidden_suspend_releases_mask(window);
        paused_clear_releases_mask(window);
        destructor_and_concurrent_reap_join_once(window);
        ddm::Host host; host.attach(reinterpret_cast<std::uintptr_t>(window));
        ddm::Scene scene; scene.width = 640; scene.height = 360;
        ddm::ViewScene view; view.view_id = 1; view.width=640; view.height=360; view.lane_height=40; view.lanes=8; view.clip={0,0,640,360};
        scene.views.push_back(view); host.update_scene(scene);
        require(pump_until([&] { const auto state=host.status_snapshot(); return state.frames>0 || state.state==ddm::HostState::Failed; }),"first frame timeout");
        auto status = host.status_snapshot();
        require(status.state!=ddm::HostState::Failed,status.error_stage.c_str());
        auto image=std::make_shared<ddm::Image>(); image->width=80; image->height=24; image->stride=320; image->pixels.resize(320*24);
        for (std::size_t i=0;i<image->pixels.size();i+=4) { image->pixels[i]=0; image->pixels[i+1]=100; image->pixels[i+2]=128; image->pixels[i+3]=128; }
        ddm::PreparedComment comment; comment.view_id=1; comment.comment_id=1; comment.width=80; comment.height=24; comment.image=image;
        auto expired=comment; expired.comment_id=2; expired.submitted_at=ddm::monotonic_seconds()-0.6;
        require(host.submit_batch({expired}).first==1,"old timestamp queues");
        require(pump_until([&] { return host.status_snapshot().engine.counters.dropped_ttl==1; }),"binding-entry timestamp retained");
        require(host.status_snapshot().engine.counters.admitted==0,"expired image never admitted");
        require(host.submit_batch({comment}).first==1,"submit");
        require(pump_until([&] { return host.status_snapshot().engine.counters.admitted==1; }),"admission timeout");
        scene.views[0].paused=true; host.update_scene(scene);
        require(pump_until([&] { return !host.status_snapshot().engine.active.empty(); }),"active");
        pump_until([] { return false; },150);
        auto frames=host.status_snapshot().frames; pump_until([] { return false; },150);
        require(host.status_snapshot().frames==frames,"paused frame spin");
        for (int cycle=0;cycle<3;++cycle) {
            scene.visible=false; host.update_scene(scene); ShowWindow(background,SW_MINIMIZE);
            require(pump_until([&] { return host.status_snapshot().state==ddm::HostState::Suspended; }),"owner minimize suspension");
            auto suspended_frames=host.status_snapshot().frames; pump_until([] { return false; },40);
            require(host.status_snapshot().frames==suspended_frames,"minimized owner does not render");
            ShowWindow(background,SW_RESTORE); ShowWindow(window,SW_SHOWNOACTIVATE);
            scene.visible=true; host.update_scene(scene);
            require(pump_until([&] { return host.status_snapshot().state==ddm::HostState::Running && host.status_snapshot().frames>suspended_frames; }),"owner restore presents");
        }
        scene.width=0; scene.height=0; host.update_scene(scene);
        require(pump_until([&] { return host.status_snapshot().state==ddm::HostState::Suspended; }),"zero size suspension");
        for (int i=0;i<100;++i) {
            scene.width=i%3 ? 500+i : 0; scene.height=i%3 ? 300+i : 0;
            ++scene.layout_rev; host.update_scene(scene);
        }
        scene.width=600; scene.height=340; ++scene.layout_rev; host.update_scene(scene);
        require(pump_until([&] { return host.status_snapshot().state==ddm::HostState::Running; }),"resize restore");
        ++scene.views[0].room_epoch; host.update_scene(scene);
        require(pump_until([&] { auto s=host.status_snapshot(); return s.engine.active.empty()&&!s.needs_visible; }),"clear transparency");
        pump_until([] { return false; },100); frames=host.status_snapshot().frames; pump_until([] { return false; },150);
        require(host.status_snapshot().frames==frames,"idle frame spin");
        ++scene.layout_rev; host.update_scene(scene);
        require(pump_until([&] { return host.status_snapshot().frames>frames; }),"explicit transparent redraw observes prior clear");

        for (int i=0;i<20;++i) {
            comment.room_epoch=scene.views[0].room_epoch; comment.comment_id=100+i;
            host.submit_batch({comment}); ++scene.views[0].room_epoch; host.update_scene(scene);
        }
        require(pump_until([&] { auto s=host.status_snapshot(); return s.engine.active.empty()&&s.engine.pending.empty()&&s.engine.processed_sequence>=22; }),"priority epoch controls settle");
        scene.views[0].paused=false; host.update_scene(scene); comment.room_epoch=scene.views[0].room_epoch; comment.comment_id=999;
        host.submit_batch({comment});
        require(pump_until([&] { return host.status_snapshot().needs_visible; }),"frame permit retained after control storm");
        host.request_close();
        require(pump_until([&] { return host.reap(); }),"two phase close timeout");
        require(host.status_snapshot().state==ddm::HostState::Stopped,"stopped state");
        const auto stopped = host.status_snapshot();
        require(stopped.engine.active.empty() && stopped.engine.pending.empty() &&
            stopped.engine.image_bytes==0 && stopped.gpu_bytes==0 && stopped.swap_chain_address==0,
            "stopped resource ledger is empty");
        require(stopped.engine.counters.admitted>0,"stopped counters remain observable");
        const auto display=host.display_statistics(0,32768);
        require(display.qpc_frequency>0 && !display.samples.empty(),"display samples retained after close");
        require(display.hwnd==reinterpret_cast<std::uintptr_t>(window) && display.swap_chain_address!=0,"display identity retained after close");
        bool observed_display=false, observed_clear=false;
        for (std::size_t i=0;i<display.samples.size();++i) {
            const auto& sample=display.samples[i];
            require(sample.record_sequence==i+1 && sample.observed_qpc>0,"display ordered timestamped records");
            require(sample.swap_chain_address==display.swap_chain_address,"display chain identity");
            if (sample.hresult==0 && sample.present_count>0 && sample.sync_qpc>0) observed_display=true;
            if (sample.frame_kind==ddm::DisplayFrameKind::Clear) observed_clear=true;
        }
        require(observed_display,"real composition display statistics observed");
        if (!observed_clear) for (const auto& sample : display.samples)
            std::cout << "display seq=" << sample.record_sequence << " hr=" << sample.hresult
                << " count=" << sample.present_count << " last=" << sample.last_present_count
                << " kind=" << static_cast<int>(sample.frame_kind) << " active=" << sample.active_count
                << " moving=" << sample.moving << " after_present=" << sample.after_present << '\n';
        require(observed_clear,"clear display history distinguished");
        const auto page=host.display_statistics(0,2);
        require(page.samples.size()==2 && page.latest_sequence==display.latest_sequence,"display page limit");
        require(host.display_statistics(display.latest_sequence,2).samples.empty(),"display cursor filters records");
        DestroyWindow(window);
        {
            HWND doomed=CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP,cls.lpszClassName,L"failure injection",WS_POPUP,40,40,80,60,nullptr,nullptr,cls.hInstance,nullptr);
            require(doomed!=nullptr,"failure test HWND");
            ddm::Host failed; failed.attach(reinterpret_cast<std::uintptr_t>(doomed)); DestroyWindow(doomed);
            failed.update_scene(scene);
            require(pump_until([&] { return failed.status_snapshot().state==ddm::HostState::Failed; }),"failure report timeout");
            const auto error=failed.status_snapshot();
            require(error.error_stage=="attach" && error.error_sequence==1,"failure details");
            failed.update_scene(scene); pump_until([] { return false; },30);
            require(failed.status_snapshot().error_sequence==1,"failure attempt once");
            bool rejected=false; try { failed.attach(reinterpret_cast<std::uintptr_t>(background)); } catch (const std::exception&) { rejected=true; }
            require(rejected,"reattach prohibited");
            failed.request_close(); require(pump_until([&] { return failed.reap(); }),"failure reap");
        }
        DestroyWindow(background); DeleteObject(cls.hbrBackground); UnregisterClassW(cls.lpszClassName,cls.hInstance);
        std::cout << "PASS: hardware composition pixels, four masks, premultiplied opacity and lifecycle; video/menu/refresh acceptance remains manual" << std::endl;
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
