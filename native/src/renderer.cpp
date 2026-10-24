#include "renderer.h"
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <dcomp.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <unordered_map>
#include <cmath>
#include <cstring>

namespace ddm {
using Microsoft::WRL::ComPtr;
RenderError::RenderError(std::string value, long result)
    : std::runtime_error(value + " failed: " + std::to_string(result)), stage(std::move(value)), code(result) {}
static void check(HRESULT result, const char* stage) { if (FAILED(result)) throw RenderError(stage, result); }
struct Vertex { float x, y, u, v, mu, mv; };
struct Texture { ComPtr<ID3D11ShaderResourceView> view; std::shared_ptr<const Image> image; std::size_t bytes = 0; };
struct Renderer::Impl {
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain2> swap;
    ComPtr<IDCompositionDevice> composition;
    ComPtr<IDCompositionTarget> target;
    ComPtr<IDCompositionVisual> visual;
    ComPtr<ID3D11RenderTargetView> rtv;
    ComPtr<ID3D11VertexShader> vs;
    ComPtr<ID3D11PixelShader> ps;
    ComPtr<ID3D11InputLayout> layout;
    ComPtr<ID3D11Buffer> vertices, constants;
    ComPtr<ID3D11BlendState> blend;
    ComPtr<ID3D11RasterizerState> raster;
    ComPtr<ID3D11SamplerState> sampler;
    std::unordered_map<const Image*, Texture> textures;
    std::unordered_map<std::uint64_t, Texture> masks;
    std::size_t mask_bytes = 0;
    Texture white;
    struct PresentMetadata {
        std::uint32_t count = 0, active_count = 0;
        bool known = false, moving = false;
        DisplayFrameKind kind = DisplayFrameKind::Unknown;
    };
    std::array<PresentMetadata, display_sample_capacity> present_metadata{};
    std::uintptr_t hwnd = 0;
    HANDLE frame = nullptr;
    int width = 0, height = 0;
    std::size_t bytes = 0;
    ~Impl() { if (frame) CloseHandle(frame); }
    Texture upload(std::shared_ptr<const Image> image) {
        if (!image || image->width <= 0 || image->height <= 0 || image->width > 16384 || image->height > 16384 ||
            image->stride < static_cast<std::int64_t>(image->width) * 4 ||
            static_cast<std::uint64_t>(image->stride) * image->height > image->pixels.size())
            throw RenderError("image validation", E_INVALIDARG);
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = image->width; desc.Height = image->height; desc.MipLevels = 1; desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM; desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_IMMUTABLE; desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA data{image->pixels.data(), static_cast<UINT>(image->stride), 0};
        ComPtr<ID3D11Texture2D> resource;
        check(device->CreateTexture2D(&desc, &data, &resource), "CreateTexture2D");
        Texture result; result.image = std::move(image);
        result.bytes = static_cast<std::size_t>(desc.Width) * desc.Height * 4;
        check(device->CreateShaderResourceView(resource.Get(), nullptr, &result.view), "CreateShaderResourceView");
        return result;
    }
    void backbuffer() {
        ComPtr<ID3D11Texture2D> buffer;
        check(swap->GetBuffer(0, IID_PPV_ARGS(&buffer)), "GetBuffer");
        check(device->CreateRenderTargetView(buffer.Get(), nullptr, &rtv), "CreateRenderTargetView");
    }
};
Renderer::Renderer() : impl_(std::make_unique<Impl>()) {}
Renderer::~Renderer() = default;
void Renderer::attach(std::uintptr_t hwnd, int width, int height) {
    auto& p = *impl_;
    if (p.device || !IsWindow(reinterpret_cast<HWND>(hwnd)) || width <= 0 || height <= 0)
        throw RenderError("attach", E_INVALIDARG);
    D3D_FEATURE_LEVEL level;
    check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        nullptr, 0, D3D11_SDK_VERSION, &p.device, &level, &p.context), "D3D11CreateDevice");
    ComPtr<IDXGIDevice> dxgi; check(p.device.As(&dxgi), "IDXGIDevice");
    ComPtr<IDXGIAdapter> adapter; check(dxgi->GetAdapter(&adapter), "GetAdapter");
    ComPtr<IDXGIFactory2> factory; check(adapter->GetParent(IID_PPV_ARGS(&factory)), "IDXGIFactory2");
    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = width; desc.Height = height; desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; desc.BufferCount = 2;
    desc.Scaling = DXGI_SCALING_STRETCH; desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    desc.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED; desc.Flags = DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
    ComPtr<IDXGISwapChain1> swap;
    check(factory->CreateSwapChainForComposition(p.device.Get(), &desc, nullptr, &swap), "CreateSwapChainForComposition");
    check(swap.As(&p.swap), "IDXGISwapChain2");
    check(p.swap->SetMaximumFrameLatency(1), "SetMaximumFrameLatency");
    p.frame = p.swap->GetFrameLatencyWaitableObject();
    if (!p.frame) throw RenderError("GetFrameLatencyWaitableObject", HRESULT_FROM_WIN32(GetLastError()));
    check(DCompositionCreateDevice(dxgi.Get(), IID_PPV_ARGS(&p.composition)), "DCompositionCreateDevice");
    check(p.composition->CreateTargetForHwnd(reinterpret_cast<HWND>(hwnd), TRUE, &p.target), "CreateTargetForHwnd");
    check(p.composition->CreateVisual(&p.visual), "CreateVisual");
    check(p.visual->SetContent(p.swap.Get()), "SetContent"); check(p.target->SetRoot(p.visual.Get()), "SetRoot");
    check(p.composition->Commit(), "Composition Commit");
    p.hwnd = hwnd;
    p.width = width; p.height = height; p.backbuffer();
    const char* shader = R"(
cbuffer Params : register(b0) { float opacity; float3 padding; };
struct V { float2 pos:POSITION; float2 uv:TEXCOORD0; float2 mask:TEXCOORD1; };
struct P { float4 pos:SV_POSITION; float2 uv:TEXCOORD0; float2 mask:TEXCOORD1; };
P vs_main(V v) { P p; p.pos=float4(v.pos,0,1); p.uv=v.uv; p.mask=v.mask; return p; }
Texture2D image:register(t0); Texture2D maskImage:register(t1); SamplerState sampleState:register(s0);
float4 ps_main(P p):SV_TARGET { return image.Sample(sampleState,p.uv)*maskImage.Sample(sampleState,p.mask).a*opacity; }
)";
    ComPtr<ID3DBlob> vb, pb, errors;
    check(D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "vs_main", "vs_4_0", 0, 0, &vb, &errors), "Compile VS");
    check(D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "ps_main", "ps_4_0", 0, 0, &pb, &errors), "Compile PS");
    check(p.device->CreateVertexShader(vb->GetBufferPointer(), vb->GetBufferSize(), nullptr, &p.vs), "CreateVertexShader");
    check(p.device->CreatePixelShader(pb->GetBufferPointer(), pb->GetBufferSize(), nullptr, &p.ps), "CreatePixelShader");
    D3D11_INPUT_ELEMENT_DESC elements[] = {{"POSITION",0,DXGI_FORMAT_R32G32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,8,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"TEXCOORD",1,DXGI_FORMAT_R32G32_FLOAT,0,16,D3D11_INPUT_PER_VERTEX_DATA,0}};
    check(p.device->CreateInputLayout(elements, 3, vb->GetBufferPointer(), vb->GetBufferSize(), &p.layout), "CreateInputLayout");
    D3D11_BUFFER_DESC bd{}; bd.ByteWidth = sizeof(Vertex) * 6; bd.Usage = D3D11_USAGE_DYNAMIC;
    bd.BindFlags = D3D11_BIND_VERTEX_BUFFER; bd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    check(p.device->CreateBuffer(&bd, nullptr, &p.vertices), "CreateBuffer vertices");
    bd.ByteWidth = 16; bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    check(p.device->CreateBuffer(&bd, nullptr, &p.constants), "CreateBuffer constants");
    D3D11_BLEND_DESC blend{}; auto& b = blend.RenderTarget[0]; b.BlendEnable = TRUE;
    b.SrcBlend = D3D11_BLEND_ONE; b.DestBlend = D3D11_BLEND_INV_SRC_ALPHA; b.BlendOp = D3D11_BLEND_OP_ADD;
    b.SrcBlendAlpha = D3D11_BLEND_ONE; b.DestBlendAlpha = D3D11_BLEND_INV_SRC_ALPHA; b.BlendOpAlpha = D3D11_BLEND_OP_ADD;
    b.RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    check(p.device->CreateBlendState(&blend, &p.blend), "CreateBlendState");
    D3D11_RASTERIZER_DESC raster{}; raster.FillMode = D3D11_FILL_SOLID; raster.CullMode = D3D11_CULL_NONE;
    raster.ScissorEnable = TRUE; raster.DepthClipEnable = TRUE;
    check(p.device->CreateRasterizerState(&raster, &p.raster), "CreateRasterizerState");
    D3D11_SAMPLER_DESC sampler{}; sampler.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP; sampler.MaxLOD = D3D11_FLOAT32_MAX;
    check(p.device->CreateSamplerState(&sampler, &p.sampler), "CreateSamplerState");
    auto white = std::make_shared<Image>(); white->width = white->height = 1; white->stride = 4; white->pixels = {255,255,255,255};
    p.white = p.upload(white);
}
void Renderer::resize(int width, int height) {
    auto& p = *impl_;
    if (width <= 0 || height <= 0 || (p.width == width && p.height == height)) return;
    p.context->OMSetRenderTargets(0, nullptr, nullptr); p.rtv.Reset();
    check(p.swap->ResizeBuffers(2, width, height, DXGI_FORMAT_UNKNOWN, DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT), "ResizeBuffers");
    p.width = width; p.height = height; p.backbuffer();
}
bool Renderer::prepare(const PreparedComment& comment) {
    auto& p = *impl_;
    if (!comment.image) throw RenderError("image validation", E_INVALIDARG);
    if (p.textures.count(comment.image.get())) return true;
    const auto bytes = static_cast<std::size_t>(comment.image->width) * comment.image->height * 4;
    if (bytes > image_budget || p.bytes > image_budget - bytes) return false;
    auto texture = p.upload(comment.image); p.bytes += texture.bytes;
    p.textures.emplace(comment.image.get(), std::move(texture)); return true;
}
void* Renderer::frame_handle() const { return impl_->frame; }
std::uint64_t Renderer::swap_chain_address() const { return reinterpret_cast<std::uint64_t>(impl_->swap.Get()); }
std::size_t Renderer::gpu_bytes() const { return impl_->bytes + impl_->mask_bytes; }
void Renderer::trim(const Scene& scene, const std::vector<RenderItem>& items) {
    auto& p = *impl_;
    std::unordered_set<const Image*> active;
    for (const auto& item : items) active.insert(item.image.get());
    for (auto it = p.textures.begin(); it != p.textures.end();) {
        if (!active.count(it->first)) { p.bytes -= it->second.bytes; it = p.textures.erase(it); }
        else ++it;
    }
    std::unordered_set<std::uint64_t> active_views;
    for (const auto& item : items) active_views.insert(item.view_id);
    for (auto it = p.masks.begin(); it != p.masks.end();) {
        const bool keep = scene.visible && active_views.count(it->first) && std::any_of(
            scene.views.begin(), scene.views.end(), [&](const ViewScene& view) {
                return view.view_id == it->first && view.visible && view.mask &&
                    view.mask == it->second.image;
            });
        if (!keep) { p.mask_bytes -= it->second.bytes; it = p.masks.erase(it); }
        else ++it;
    }
}
void Renderer::draw(const Scene& scene, const std::vector<RenderItem>& items) {
    auto& p = *impl_;
    const float clear[4]{}; p.context->ClearRenderTargetView(p.rtv.Get(), clear);
    auto target = p.rtv.Get(); p.context->OMSetRenderTargets(1, &target, nullptr);
    p.context->OMSetBlendState(p.blend.Get(), nullptr, 0xffffffff);
    p.context->RSSetState(p.raster.Get());
    D3D11_VIEWPORT viewport{0,0,static_cast<float>(p.width),static_cast<float>(p.height),0,1};
    p.context->RSSetViewports(1, &viewport);
    p.context->IASetInputLayout(p.layout.Get()); p.context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    UINT stride = sizeof(Vertex), offset = 0; auto vertices = p.vertices.Get();
    p.context->IASetVertexBuffers(0,1,&vertices,&stride,&offset);
    p.context->VSSetShader(p.vs.Get(),nullptr,0); p.context->PSSetShader(p.ps.Get(),nullptr,0);
    auto sampler = p.sampler.Get(); p.context->PSSetSamplers(0,1,&sampler);
    auto constants = p.constants.Get(); p.context->PSSetConstantBuffers(0,1,&constants);
    for (const auto& view : scene.views) {
        if (!view.visible || view.width <= 0 || view.height <= 0 || view.clip.width <= 0 || view.clip.height <= 0) continue;
        const bool active = std::any_of(items.begin(), items.end(), [&](const RenderItem& item) {
            return item.view_id == view.view_id;
        });
        if (!active) continue;
        D3D11_RECT clip{std::max(0,view.clip.x),std::max(0,view.clip.y),std::min(p.width,view.clip.x+view.clip.width),std::min(p.height,view.clip.y+view.clip.height)};
        if (clip.right <= clip.left || clip.bottom <= clip.top) continue;
        p.context->RSSetScissorRects(1,&clip);
        Texture* mask = &p.white;
        if (view.mask) {
            auto found = p.masks.find(view.view_id);
            if (found == p.masks.end() || found->second.image != view.mask) {
                const auto previous = found == p.masks.end() ? 0 : found->second.bytes;
                const auto bytes = static_cast<std::size_t>(view.mask->width) * view.mask->height * 4;
                if (bytes > image_budget || p.mask_bytes - previous > image_budget - bytes)
                    throw RenderError("mask budget", E_OUTOFMEMORY);
                auto texture = p.upload(view.mask);
                p.mask_bytes = p.mask_bytes - previous + texture.bytes;
                p.masks[view.view_id] = std::move(texture);
                found = p.masks.find(view.view_id);
            }
            mask = &found->second;
        }
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check(p.context->Map(p.constants.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped), "Map constants");
        const float params[4]{static_cast<float>(std::clamp(view.opacity,0.0,1.0)),0,0,0}; memcpy(mapped.pData,params,sizeof(params)); p.context->Unmap(p.constants.Get(),0);
        for (const auto& item : items) {
            if (item.view_id != view.view_id) continue;
            auto found = p.textures.find(item.image.get()); if (found == p.textures.end()) continue;
            const float l = static_cast<float>(view.clip.x + item.x * view.clip.width/view.width);
            const float t = static_cast<float>(view.clip.y + item.y * view.clip.height/view.height);
            const float r = l + static_cast<float>(item.width * view.clip.width/view.width);
            const float b = t + static_cast<float>(item.height * view.clip.height/view.height);
            auto vertex = [&](float x,float y,float u,float v) { return Vertex{x*2/p.width-1,1-y*2/p.height,u,v,(x-view.clip.x)/view.clip.width,(y-view.clip.y)/view.clip.height}; };
            const Vertex quad[]{vertex(l,t,0,0),vertex(r,t,1,0),vertex(l,b,0,1),vertex(l,b,0,1),vertex(r,t,1,0),vertex(r,b,1,1)};
            check(p.context->Map(p.vertices.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped), "Map vertices");
            memcpy(mapped.pData,quad,sizeof(quad)); p.context->Unmap(p.vertices.Get(),0);
            ID3D11ShaderResourceView* resources[]{found->second.view.Get(),mask->view.Get()};
            p.context->PSSetShaderResources(0,2,resources); p.context->Draw(6,0);
        }
    }
    ID3D11ShaderResourceView* empty[2]{}; p.context->PSSetShaderResources(0,2,empty);
    check(p.swap->Present(1,0), "Present");
}
}

namespace ddm {
DisplaySample Renderer::display_sample(bool after_present, bool moving, std::uint32_t active_count,
                                      DisplayFrameKind kind) {
    auto& p = *impl_;
    DisplaySample result;
    result.after_present = after_present;
    result.hwnd = p.hwnd; result.swap_chain_address = swap_chain_address();
    LARGE_INTEGER observed{};
    if (!p.swap) { result.hresult = result.last_present_hresult = static_cast<std::uint32_t>(E_POINTER); return result; }
    UINT last = 0;
    const auto last_hr = p.swap->GetLastPresentCount(&last);
    result.last_present_hresult = static_cast<std::uint32_t>(last_hr); result.last_present_count = last;
    if (after_present && SUCCEEDED(last_hr))
        p.present_metadata[last % display_sample_capacity] = {last,active_count,true,moving,kind};
    DXGI_FRAME_STATISTICS stats{};
    const auto hr = p.swap->GetFrameStatistics(&stats);
    QueryPerformanceCounter(&observed); result.observed_qpc = observed.QuadPart;
    result.hresult = static_cast<std::uint32_t>(hr);
    result.present_count = stats.PresentCount; result.present_refresh_count = stats.PresentRefreshCount;
    result.sync_refresh_count = stats.SyncRefreshCount; result.sync_qpc = stats.SyncQPCTime.QuadPart;
    if (SUCCEEDED(hr) && stats.PresentCount != 0) {
        const auto& metadata = p.present_metadata[stats.PresentCount % display_sample_capacity];
        if (metadata.known && metadata.count == stats.PresentCount) {
            result.moving = metadata.moving; result.active_count = metadata.active_count; result.frame_kind = metadata.kind;
        }
    }
    return result;
}
}
