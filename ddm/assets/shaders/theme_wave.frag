#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float progress;
    vec2 viewportSize;
    vec2 waveOrigin;
    float maxRadius;
} ubuf;
layout(binding = 1) uniform sampler2D source;
void main() {
    float distanceFromOrigin = length(qt_TexCoord0 * ubuf.viewportSize - ubuf.waveOrigin);
    float radius = ubuf.progress * ubuf.maxRadius;
    float coverage = smoothstep(radius - 1.0, radius + 1.0, distanceFromOrigin);
    if (ubuf.progress <= 0.0) coverage = 1.0;
    if (ubuf.progress >= 1.0) coverage = 0.0;
    fragColor = texture(source, qt_TexCoord0) * ubuf.qt_Opacity * coverage;
}
