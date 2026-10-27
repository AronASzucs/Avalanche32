#!/usr/bin/env python3
"""Generate 3D renders and per-layer plots of the PCB into Images/.

Runs outside KiCad using kicad-cli (KiCad 9 or newer). Reads the *saved* board file,
so save in KiCad first.

    python scripts/generate_images.py                 # everything, high quality
    python scripts/generate_images.py --quality basic # faster 3D renders
    python scripts/generate_images.py --skip-3d       # layer plots only
    python scripts/generate_images.py --skip-layers   # 3D renders only

Output:
    Images/3D/      top, bottom, side and isometric renders (PNG, transparent background,
                    zoomed to fit and cropped to the board; needs Pillow: pip install pillow)
    Images/Layers/  each layer, front/back composites and drill map (PNG)

Layer plots are exported by KiCad as SVG and rasterised with PyMuPDF
(pip install pymupdf). Without PyMuPDF the SVGs are kept instead.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "Images"

# name, kicad-cli render args, zoom, width, height
VIEWS_3D = [
    ("top", ["--side", "top"], 0.95, 1920, 1200),
    ("bottom", ["--side", "bottom"], 0.95, 1920, 1200),
    ("side_front", ["--side", "front"], 3.5, 1920, 520),
    ("side_back", ["--side", "back"], 3.5, 1920, 520),
    ("side_left", ["--side", "left"], 3.5, 1400, 520),
    ("side_right", ["--side", "right"], 3.5, 1400, 520),
    ("iso_front_left", ["--rotate", "-55,0,-25"], 1.0, 1920, 1200),
    ("iso_front_right", ["--rotate", "-55,0,25"], 1.0, 1920, 1200),
    ("iso_back_left", ["--rotate", "-55,0,155"], 1.0, 1920, 1200),
    ("iso_back_right", ["--rotate", "-55,0,-155"], 1.0, 1920, 1200),
    ("iso_bottom_front", ["--side", "bottom", "--rotate", "-55,0,-25"], 1.0, 1920, 1200),
    ("iso_bottom_back", ["--rotate", "125,0,-25"], 1.0, 1920, 1200),
]

# name, layers, mirror (bottom-side layers are mirrored so they read as seen from below)
LAYER_PLOTS = [
    ("front_composite", "F.Cu,F.Silkscreen,Edge.Cuts", False),
    ("back_composite", "B.Cu,B.Silkscreen,Edge.Cuts", True),
    ("copper_both", "B.Cu,F.Cu,Edge.Cuts", False),
    ("F_Cu", "F.Cu,Edge.Cuts", False),
    ("B_Cu", "B.Cu,Edge.Cuts", True),
    ("F_Silkscreen", "F.Silkscreen,Edge.Cuts", False),
    ("B_Silkscreen", "B.Silkscreen,Edge.Cuts", True),
    ("F_Mask", "F.Mask,Edge.Cuts", False),
    ("B_Mask", "B.Mask,Edge.Cuts", True),
    ("F_Paste", "F.Paste,Edge.Cuts", False),
    ("B_Paste", "B.Paste,Edge.Cuts", True),
    ("F_Fab", "F.Fab,Edge.Cuts", False),
    ("B_Fab", "B.Fab,Edge.Cuts", True),
    ("F_Courtyard", "F.Courtyard,Edge.Cuts", False),
    ("B_Courtyard", "B.Courtyard,Edge.Cuts", True),
    ("Edge_Cuts", "Edge.Cuts", False),
]

FIT_FILL = 0.98               # 3D renders: fraction of the frame the board fills before cropping
ALPHA_THRESHOLD = 8           # 3D renders: pixels at or below this alpha count as empty when cropping
PLOT_BACKGROUND = "#001023"  # KiCad's PCB editor background; the default layer colours need a dark page
CROP_MARGIN_MM = 2.0          # padding kept around the board outline in layer PNGs


def find_kicad_cli():
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).is_file():
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidates = sorted(glob.glob(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe"),
                        key=lambda p: [int(n) for n in re.findall(r"\d+", Path(p).parts[-3])])
    candidates += ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli", "/usr/bin/kicad-cli"]
    for c in reversed(candidates):
        if Path(c).is_file():
            return c
    sys.exit("kicad-cli not found. Install KiCad 9+ or set the KICAD_CLI environment variable.")


def find_board():
    boards = [p for p in ROOT.glob("*.kicad_pcb") if not p.name.startswith("~")]
    if len(boards) != 1:
        sys.exit(f"Expected one .kicad_pcb in {ROOT}, found {len(boards)}.")
    return boards[0]


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {' '.join(cmd)}\n{result.stdout}{result.stderr}")
        return False
    return True


def content_bbox(png):
    """Bounding box (x0, y0, x1, y1) of the non-transparent pixels, or None."""
    from PIL import Image
    with Image.open(png) as im:
        return im.getchannel("A").point(lambda a: 255 if a > ALPHA_THRESHOLD else 0).getbbox()


def fit_zoom(bbox, w, h):
    """Zoom multiplier that makes the content just fill a w x h frame.

    kicad-cli zooms about the image centre, so the side furthest from the centre limits it.
    """
    x0, y0, x1, y1 = bbox
    half_w = max(w / 2 - x0, x1 - w / 2)
    half_h = max(h / 2 - y0, y1 - h / 2)
    return FIT_FILL * min(w / 2 / half_w, h / 2 / half_h)


def render_3d(cli, board, quality):
    from PIL import Image
    out = IMAGES / "3D"
    out.mkdir(parents=True, exist_ok=True)
    # "high" forces KiCad's plated/bare copper mode, which draws all copper under the mask
    # a fixed bare-copper brown; "user" (+ --floor) keeps the stackup finish colour instead
    q = ["--quality", "user", "--floor"] if quality == "high" else ["--quality", quality]
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, args, zoom, w, h) in enumerate(VIEWS_3D, 1):
            print(f"  [{i}/{len(VIEWS_3D)}] {name}")
            png = out / f"{name}.png"
            png.unlink(missing_ok=True)   # kicad-cli can exit 0 without writing (e.g. file open in a viewer)

            # Quick basic-quality pass to measure the content, then zoom so it fills the frame
            probe = Path(tmp) / f"{name}.png"
            run([cli, "pcb", "render", "--quality", "basic", "--zoom", str(zoom),
                 "-w", str(w), "-h", str(h), *args, "-o", str(probe), str(board)])
            bbox = content_bbox(probe) if probe.is_file() else None
            if bbox:
                zoom *= fit_zoom(bbox, w, h)

            run([cli, "pcb", "render", *q, "--zoom", f"{zoom:.4f}",
                 "-w", str(w), "-h", str(h), *args, "-o", str(png), str(board)])
            if not png.is_file():
                failed.append(name)
                continue
            # Crop away whatever empty margin is left on the non-limiting axis
            bbox = content_bbox(png)
            if bbox:
                with Image.open(png) as im:
                    im.load()
                im.crop(bbox).save(png)
    if failed:
        print(f"  WARNING: not written: {', '.join(failed)} (close any viewer holding them and re-run)")


VIEWBOX_RE = re.compile(r'viewBox="([-\d.eE]+)[ ,]+([-\d.eE]+)[ ,]+([-\d.eE]+)[ ,]+([-\d.eE]+)"')


def add_background(svg_path, colour):
    """Insert an opaque background rect so pale layer colours stay visible."""
    text = svg_path.read_text(encoding="utf-8")
    vb = VIEWBOX_RE.search(text)
    tag_end = re.search(r"<svg\b[^>]*>", text)
    if not vb or not tag_end:
        return
    x, y, w, h = vb.groups()
    rect = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{colour}"/>'
    svg_path.write_text(text[:tag_end.end()] + rect + text[tag_end.end():], encoding="utf-8")


def board_rect(edge_svg):
    """Board outline bounds (x0, y0, x1, y1, page_width) in SVG units, from an Edge.Cuts-only plot.

    KiCad sizes the plot page to every item on the board, so parts overhanging the edge
    (e.g. the ESP32 antenna courtyard) widen it; the layer PNGs are cropped to this instead.
    """
    text = edge_svg.read_text(encoding="utf-8")
    nums = [float(n) for d in re.findall(r'\bd="([^"]*)"', text)
            for n in re.findall(r"-?\d+\.?\d*", d)]
    if len(nums) < 4:
        return None
    xs, ys = nums[0::2], nums[1::2]
    page_w = float(VIEWBOX_RE.search(text).group(3))
    return min(xs), min(ys), max(xs), max(ys), page_w


def rasterise(svg_path, png_path, width_px, crop=None, mirror=False, background=PLOT_BACKGROUND):
    import pymupdf
    add_background(svg_path, background)
    with pymupdf.open(svg_path) as doc:
        page = doc[0]
        clip = None
        if crop:
            x0, y0, x1, y1, page_w = crop
            if mirror:
                x0, x1 = page_w - x1, page_w - x0
            k = page.rect.width / page_w          # SVG units -> PDF points
            m = CROP_MARGIN_MM
            clip = pymupdf.Rect((x0 - m) * k, (y0 - m) * k, (x1 + m) * k, (y1 + m) * k) & page.rect
        z = width_px / (clip or page.rect).width
        page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, alpha=False).save(png_path)


def plot_layers(cli, board, width_px):
    out = IMAGES / "Layers"
    out.mkdir(parents=True, exist_ok=True)
    try:
        import pymupdf  # noqa: F401
        have_raster = True
    except ImportError:
        have_raster = False
        print("  PyMuPDF not installed (pip install pymupdf) - keeping SVGs instead of PNGs")

    def export_svg(svg, layers, mirror):
        cmd = [cli, "pcb", "export", "svg", "--mode-single", "--layers", layers,
               "--page-size-mode", "2", "--exclude-drawing-sheet", "--check-zones",
               "--sketch-pads-on-fab-layers", "-o", str(svg), str(board)]
        if mirror:
            cmd.insert(4, "--mirror")
        return run(cmd)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        edge_svg = tmp / "_outline.svg"
        crop = board_rect(edge_svg) if export_svg(edge_svg, "Edge.Cuts", False) else None

        for i, (name, layers, mirror) in enumerate(LAYER_PLOTS, 1):
            print(f"  [{i}/{len(LAYER_PLOTS)}] {name}")
            svg = tmp / f"{name}.svg"
            if not export_svg(svg, layers, mirror):
                continue
            if have_raster:
                rasterise(svg, out / f"{name}.png", width_px, crop, mirror)
            else:
                shutil.copy(svg, out / f"{name}.svg")

        # The drill map is drawn in black with a legend below the board: white page, no crop
        print("  drill_map")
        drill_dir = tmp / "drill"
        drill_dir.mkdir()
        if run([cli, "pcb", "export", "drill", "--generate-map", "--map-format", "svg",
                "-o", str(drill_dir) + os.sep, str(board)]):
            for svg in drill_dir.glob("*.svg"):
                suffix = "_NPTH" if "NPTH" in svg.stem else "_PTH" if "PTH" in svg.stem else ""
                if have_raster:
                    rasterise(svg, out / f"drill_map{suffix}.png", width_px, background="#FFFFFF")
                else:
                    shutil.copy(svg, out / f"drill_map{suffix}.svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quality", choices=["basic", "high"], default="high",
                    help="3D render quality (default: high)")
    ap.add_argument("--layer-width", type=int, default=3000,
                    help="width in pixels of the layer PNGs (default: 3000)")
    ap.add_argument("--skip-3d", action="store_true", help="don't render 3D views")
    ap.add_argument("--skip-layers", action="store_true", help="don't plot layers")
    args = ap.parse_args()

    cli = find_kicad_cli()
    board = find_board()
    print(f"Board:     {board.name}\nkicad-cli: {cli}\nOutput:    {IMAGES}")

    if not args.skip_3d:
        print("3D renders:")
        render_3d(cli, board, args.quality)
    if not args.skip_layers:
        print("Layer plots:")
        plot_layers(cli, board, args.layer_width)
    print("Done.")


if __name__ == "__main__":
    main()
