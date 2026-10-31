#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 tint;
};
layout(binding = 1) uniform sampler2D source;
void main() {
    vec4 pixel = texture(source, qt_TexCoord0);
    // Preserve the white ServiceM8 mark, removing its green tile.
    float white = min(pixel.r, min(pixel.g, pixel.b));
    float coverage = clamp((white - 0.55) / 0.45, 0.0, 1.0);
    float alpha = coverage * pixel.a * tint.a * qt_Opacity;
    fragColor = vec4(tint.rgb * alpha, alpha);
}
