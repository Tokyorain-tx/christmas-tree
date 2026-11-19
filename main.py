import os
import numpy as np
import moderngl
import glfw

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

WIN_W, WIN_H = 1400, 850

FULLSCREEN_VERT = """
#version 330
in vec2 in_pos;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

FRAG = """
#version 330
uniform vec2 res;
uniform float time;
uniform float zoom;
uniform sampler2D text_tex;
uniform vec2 tex_size;
uniform float text_h_world;
uniform float text_skew;
uniform vec2 text_center;
out vec4 f_color;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
        mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x),
        u.y);
}

// 圆锥侧面轮廓，从顶到底半径线性变大，稍微鼓一点
const float Y_TOP = 0.45;
const float Y_BOT = -0.35;
const float R_MAX = 0.5;

float get_radius(float y) {
    if (y > Y_TOP || y < Y_BOT) return 0.0;
    float t = (Y_TOP - y) / (Y_TOP - Y_BOT);
    return t * R_MAX * (1.0 + 0.1 * sin(t * 3.14));
}

// 黄 -> 绿 -> 红 -> 黄
vec3 cycle_color(float t) {
    float ph = fract(t);
    vec3 c_y = vec3(1.00, 0.72, 0.12);
    vec3 c_g = vec3(0.20, 1.00, 0.30);
    vec3 c_r = vec3(1.00, 0.10, 0.08);
    if (ph < 0.3333) return mix(c_y, c_g, smoothstep(0.0, 0.3333, ph));
    if (ph < 0.6667) return mix(c_g, c_r, smoothstep(0.3333, 0.6667, ph));
    return mix(c_r, c_y, smoothstep(0.6667, 1.0, ph));
}

// 顶上那颗星
vec3 top_star(vec2 p, float t, vec3 tint) {
    vec2 d = p - vec2(0.0, Y_TOP + 0.05);
    float r = length(d);
    float ang = t * 0.5;
    vec2 dr = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * d;
    float core = exp(-r * r / (0.008 * 0.008)) * 3.0;
    float glow = exp(-r * 15.0) * 1.5;
    float rayX = exp(-abs(dr.x) / 0.004) * exp(-abs(dr.y) * 10.0) * 1.2;
    float rayY = exp(-abs(dr.y) / 0.004) * exp(-abs(dr.x) * 10.0) * 1.2;
    float flick = 0.9 + 0.1 * sin(t * 3.0);
    vec3 base = mix(vec3(1.0, 0.88, 0.55), tint, 0.8);
    vec3 halo = mix(base, vec3(1.0, 0.95, 0.85), 0.25);
    return (base * core + halo * (glow + rayX + rayY)) * flick;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * res) / res.y;
    uv /= zoom;
    uv.y += 0.12;
    float t = time;
    vec3 band_col = cycle_color(t * 0.12);

    // 深空底色
    vec3 col = mix(vec3(0.005, 0.01, 0.03), vec3(0.02, 0.05, 0.10),
                   smoothstep(-0.4, 0.5, uv.y));

    // 背景星星
    vec2 star_cell = floor(uv * 100.0);
    float sh = hash21(star_cell);
    float star_mask = smoothstep(0.985, 0.995, sh);
    if (star_mask > 0.0) {
        vec2 fr = fract(uv * 100.0);
        float d = length(fr - 0.5);
        float star_glow = exp(-d * 12.0);
        float phase = hash21(star_cell + 19.19) * 6.2832;
        float freq  = 1.5 + hash21(star_cell + 47.0) * 3.5;
        float twinkle = 0.5 + 0.5 * sin(t * freq + phase);
        vec3 star_col = mix(vec3(0.85, 0.90, 1.00),
                            vec3(1.00, 0.92, 0.80),
                            hash21(star_cell + 3.7));
        col += star_col * star_glow * (0.35 + 0.65 * twinkle) * star_mask;
    }

    // 螺旋灯带：圆锥面
    float tree_R = get_radius(uv.y);
    if (abs(uv.x) < tree_R) {
        float z = sqrt(max(0.0, tree_R * tree_R - uv.x * uv.x));
        float z_norm = z / max(tree_R, 0.001);
        float angle = atan(uv.x, z);
        float spiral_phase = angle * 4.0 + (Y_TOP - uv.y) * 25.0 - t * 2.0;
        float line = pow(max(0.0, sin(spiral_phase)), 32.0);
        float glow = exp(-abs(sin(spiral_phase)) * 5.0) * 0.5;
        vec3 light_color = band_col;
        float pulse = pow(0.5 + 0.5 * sin((Y_TOP - uv.y) * 30.0 - t * 8.0), 4.0);
        light_color += light_color * pulse * 0.8;
        float depth_fade = smoothstep(-0.2, 0.5, z_norm);
        col += light_color * (line * 4.0 + glow) * depth_fade;
    }

    col += top_star(uv, t, band_col);

    // 标题文字，斜切
    float tex_aspect = tex_size.x / tex_size.y;
    float text_w_world = text_h_world * tex_aspect;
    vec2 local = uv - text_center;
    local.x -= local.y * text_skew;
    vec2 tuv = local / vec2(text_w_world, text_h_world) + 0.5;

    if (tuv.x >= 0.0 && tuv.x <= 1.0 && tuv.y >= 0.0 && tuv.y <= 1.0) {
        float mask = texture(text_tex, tuv).r;
        if (mask > 0.01) {
            float breathe = 0.75 + 0.25 * sin(t * 1.5);
            float sweep = fract(t * 0.2);
            float dx = tuv.x - sweep;
            float sweep_glow = exp(-dx * dx * 260.0) * 2.5;
            col += band_col * mask * (1.5 * breathe + sweep_glow);
        }
    }

    // 飘雪
    for (int i = 0; i < 50; i++) {
        float fi = float(i);
        float sx = hash21(vec2(fi, 0.0)) * 2.0 - 1.0;
        float sp = 0.1 + hash21(vec2(fi, 1.0)) * 0.15;
        float sy = 0.6 - mod(t * sp + hash21(vec2(fi, 2.0)) * 1.5, 1.5);
        float wobble = sin(t * 0.8 + fi) * 0.03;
        float sd = length(uv - vec2(sx + wobble, sy));
        float size = 200.0 + hash21(vec2(fi, 3.0)) * 300.0;
        col += vec3(0.9, 0.95, 1.0) * exp(-sd * size) * 0.8;
    }

    // 泛光 + 暗角
    float brightness = dot(col, vec3(0.299, 0.587, 0.114));
    if (brightness > 0.6) {
        col += col * (brightness - 0.6) * 1.2;
    }
    float vig = 1.0 - length(uv * 0.7) * 0.5;
    col *= vig;

    f_color = vec4(col, 1.0);
}
"""

# 字体候选列表
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def find_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def build_text_texture(text, target_height=72, skew=0.5):
    if not HAS_PIL:
        raise RuntimeError("需要 Pillow 才能渲染矢量字体：pip install pillow")
    font_path = find_font()
    if font_path is None:
        raise RuntimeError("未找到可用字体文件，请检查 FONT_CANDIDATES")

    big_size = 128
    font = ImageFont.truetype(font_path, big_size)
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img = Image.new('L', (text_w, text_h), 0)
    draw = ImageDraw.Draw(img)
    draw.text((-bbox[0], -bbox[1]), text, fill=255, font=font)

    scale = target_height / text_h
    new_w = max(1, int(text_w * scale))
    img = img.resize((new_w, target_height), Image.LANCZOS)

    pad_x = int(target_height * skew / 2) + 2
    padded = Image.new('L', (new_w + pad_x * 2, target_height), 0)
    padded.paste(img, (pad_x, 0))

    arr = np.array(padded, dtype=np.uint8)
    arr = np.flipud(arr)  # GL纹理Y轴朝上
    return arr


def main():
    glfw.init()
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    win = glfw.create_window(WIN_W, WIN_H, "圣诞树流光版 · Merry Christmas", None, None)
    glfw.make_context_current(win)
    glfw.swap_interval(1)

    ctx = moderngl.create_context()

    quad = np.array([
        -1, -1,  1, -1,  1, 1,
        -1, -1,  1,  1, -1, 1,
    ], 'f4')

    prog = ctx.program(vertex_shader=FULLSCREEN_VERT, fragment_shader=FRAG)
    vao = ctx.vertex_array(prog, [(ctx.buffer(quad.tobytes()), '2f', 'in_pos')])

    SKEW = 0.5
    TEXT_H_WORLD = 0.078
    img = build_text_texture("Merry Christmas Lin", target_height=72, skew=SKEW)
    tex_h, tex_w = img.shape

    text_tex = ctx.texture((tex_w, tex_h), 1, img.tobytes())
    text_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
    text_tex.repeat_x = False
    text_tex.repeat_y = False
    text_tex.use(0)

    prog["text_tex"].value = 0
    prog["tex_size"].value = (float(tex_w), float(tex_h))
    prog["text_h_world"].value = TEXT_H_WORLD
    prog["text_skew"].value = SKEW
    prog["text_center"].value = (0.0, 0.575)

    zoom = 1.0

    def on_scroll(w, xoff, yoff):
        nonlocal zoom
        zoom *= 1.0 + yoff * 0.08
        zoom = max(0.5, min(3.0, zoom))

    glfw.set_scroll_callback(win, on_scroll)

    while not glfw.window_should_close(win):
        if glfw.get_key(win, glfw.KEY_ESCAPE) == glfw.PRESS:
            break

        t = glfw.get_time()
        fw, fh = glfw.get_framebuffer_size(win)
        if fw <= 0 or fh <= 0:
            glfw.swap_buffers(win)
            glfw.poll_events()
            continue

        prog["res"].value = (float(fw), float(fh))
        prog["time"].value = t
        prog["zoom"].value = zoom

        ctx.clear(0.0, 0.0, 0.0)
        vao.render(moderngl.TRIANGLES)

        glfw.swap_buffers(win)
        glfw.poll_events()

    glfw.terminate()


if __name__ == "__main__":
    main()
