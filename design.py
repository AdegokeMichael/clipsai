#!/usr/bin/env python3
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from clipsai import resize  # Requires your pyannote token (PYANNOTE_AUTH_TOKEN)

# ========= Path configuration =========
# Project root: this file lives in /home/michael_adegoke/clipsai/
PROJECT_DIR = Path(__file__).resolve().parent

# Media base: large files live outside the repo under /home/michael_adegoke/
BASE_DIR = PROJECT_DIR.parent

# Inputs/outputs (unchanged behavior)
INPUT_DIR = BASE_DIR / "clips"            # raw clips from quicktest.py (clip_1.mp4…)
OUTPUT_DIR = BASE_DIR / "designed"        # final rendered outputs (*_vertical.mp4)

# Template lives inside the repo now:
TEMPLATE_PATH = PROJECT_DIR / "templates" / "emigr8_vertical.png"

# Canvas
OUTPUT_W, OUTPUT_H = 1080, 1920

# Subtitle styling (libass / ffmpeg subtitles filter)
CAPTION_FONT = "DejaVu Sans"  # change to a font available on your system
CAPTION_STYLE = (
    f"FontName={CAPTION_FONT},"
    "FontSize=13,"
    "PrimaryColour=&H00FFFFFF&,"   # white text
    "BackColour=&H80000000&,"      # ~50% opaque black box
    "Outline=0,"
    "Shadow=0,"
    "BorderStyle=3,"               # boxed background
    "Alignment=2,"                 # bottom center
    "MarginV=120,"                 # lift above footer/template
    "Bold=1,"
    "WrapStyle=2"                  # better wrapping
)

# pyannote auth (used by clipsai.resize)
PYANNOTE_TOKEN = os.environ.get("PYANNOTE_AUTH_TOKEN", "")

# Ensure output dir exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ========= Helpers =========
def run(cmd: list):
    """Run a subprocess, echoing the command for debugging."""
    print("→", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


def get_video_dimensions(video_path: Path) -> Tuple[int, int]:
    """Get video width and height using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    w, h = map(int, result.stdout.strip().split(','))
    return w, h


def expand_crop_box(
    crop_box: Tuple[int, int, int, int],
    video_w: int,
    video_h: int,
    expansion_factor: float = 1.8
) -> Tuple[int, int, int, int]:
    """
    Expand a crop box by a factor while maintaining aspect ratio and staying in bounds.

    Args:
        crop_box: (x, y, w, h) original crop coordinates
        video_w, video_h: Original video dimensions
        expansion_factor: How much to expand (1.8 = 80% larger, 2.0 = double size)

    Returns:
        Expanded (x, y, w, h) crop box
    """
    x, y, w, h = crop_box

    # Calculate center of original crop
    center_x = x + w / 2
    center_y = y + h / 2

    # Expand dimensions
    new_w = int(w * expansion_factor)
    new_h = int(h * expansion_factor)

    # Recenter
    new_x = int(center_x - new_w / 2)
    new_y = int(center_y - new_h / 2)

    # Clamp to video bounds
    new_x = max(0, new_x)
    new_y = max(0, new_y)
    new_w = min(new_w, video_w - new_x)
    new_h = min(new_h, video_h - new_y)

    return (new_x, new_y, new_w, new_h)


def pick_primary_crop(crops_obj) -> Optional[Tuple[int, int, int, int]]:
    """
    Pick a stable crop from clipsai.resize() output.
    Assumes items in crops_obj.segments have start/end/x/y/w/h.
    """
    segs = getattr(crops_obj, "segments", None)
    if not segs:
        return None
    segs = sorted(segs, key=lambda s: (getattr(s, "end", 0) - getattr(s, "start", 0)), reverse=True)
    s = segs[0]
    x, y = int(getattr(s, "x", 0)), int(getattr(s, "y", 0))
    w, h = int(getattr(s, "w", 0)), int(getattr(s, "h", 0))
    return (x, y, w, h) if min(w, h) > 0 else None


def escape_for_subtitles(path: Path) -> str:
    """
    Escape SRT path for ffmpeg's subtitles filter (libass).
    Handles spaces, colons, commas, backslashes, and single quotes.
    """
    s = str(path)
    return (
        s.replace("\\", "\\\\")
         .replace(":", "\\:")
         .replace(",", "\\,")
         .replace("'", "\\'")
    )


def build_filtergraph(
    crop_box: Optional[Tuple[int, int, int, int]],
    out_w: int,
    out_h: int,
    srt_path: Optional[Path],
) -> str:
    """
    Filter graph:
      - Background: scale to cover, blur, crop to WxH
      - Foreground: smart/center 9:16 crop, scale to fit, center overlay
      - Optional: burn subtitles (with escaped force_style)
      - Overlay PNG template on top
    """
    parts = []

    # Background: scale-to-cover → blur → crop
    parts.append(
        f"[0:v]"
        f"scale='if(gte(iw/ih,{out_w}/{out_h}),-1,{out_w})'"
        f":'if(gte(iw/ih,{out_w}/{out_h}),{out_h},-1)',"
        f"boxblur=24:1,"
        f"crop={out_w}:{out_h}[bg]"
    )

    # Foreground crop (smart or center 9:16)
    if crop_box and all(v > 0 for v in crop_box):
        x, y, w, h = crop_box
        parts.append(f"[0:v]crop={w}:{h}:{x}:{y}[fg]")
    else:
        # Center 9:16 crop (escapes commas for ffmpeg 4.x)
        parts.append(
            "[0:v]"
            "crop="
            "iw*min(1.0\\,ih/iw*9/16):"
            "ih*min(1.0\\,iw/ih*16/9):"
            "(iw - iw*min(1.0\\,ih/iw*9/16))/2:"
            "(ih - ih*min(1.0\\,iw/ih*16/9))/2[fg]"
        )

    # Fit FG to canvas, keep AR; composite over blurred BG
    parts.append(f"[fg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fgs]")
    parts.append("[bg][fgs]overlay=(W-w)/2:(H-h)/2[base]")

    # Optional subtitles (burn before template)
    base_label = "[base]"
    if srt_path:
        style_escaped = CAPTION_STYLE.replace(",", "\\,")
        srt_escaped = escape_for_subtitles(srt_path)
        parts.append(f"{base_label}subtitles='{srt_escaped}':force_style='{style_escaped}'[base2]")
        base_label = "[base2]"

    # Template overlay on top (assumed full-canvas PNG with transparency)
    parts.append(f"{base_label}[1:v]overlay=0:0[outv]")

    return ",".join(parts)


def ff_design(
    src: Path,
    dst: Path,
    overlay_png: Path,
    crop_box: Optional[Tuple[int, int, int, int]],
    out_w: int,
    out_h: int,
    srt_path: Optional[Path] = None,
):
    vf = build_filtergraph(crop_box=crop_box, out_w=out_w, out_h=out_h, srt_path=srt_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),              # 0: video with audio
        "-i", str(overlay_png),      # 1: PNG template
        "-filter_complex", vf,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "copy",
        str(dst)
    ]
    run(cmd)


# ========= Main =========
def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Design vertical 9:16 video with template and (single) styled subtitle burn."
    )

    ap.add_argument("--input_dir", default=str(INPUT_DIR))
    ap.add_argument("--output_dir", default=str(OUTPUT_DIR))
    ap.add_argument("--template", default=str(TEMPLATE_PATH))
    ap.add_argument("--width", type=int, default=OUTPUT_W)
    ap.add_argument("--height", type=int, default=OUTPUT_H)
    ap.add_argument("--pyannote_token", default=PYANNOTE_TOKEN)

    # NEW: Crop expansion control
    ap.add_argument("--crop_expansion", type=float, default=3.0,
                    help="Factor to expand face crops (1.8=80%% larger for torso shots, 1.0=no expansion)")
    ap.add_argument("--disable_smart_crop", action="store_true",
                    help="Skip face detection and use center crop (recommended for Zoom meetings)")

    # Subtitle controls (default=auto to use SRTs made by subtitles.py)
    ap.add_argument("--subs_mode", choices=["off", "auto", "file"], default="off",
                    help="off=never burn; auto=use clip.srt or from --subs_dir; file=use --subs_file for every clip")
    ap.add_argument("--subs_dir", default=str(BASE_DIR / "subtitles"),
                    help="Where .srt files live when subs_mode=off")
    ap.add_argument("--subs_file", default="", help="Single .srt to burn when subs_mode=file")

    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    template = Path(args.template)
    if not template.exists():
        raise FileNotFoundError(f"Template PNG not found: {template}")

    inputs = sorted(in_dir.glob("clip_*.mp4"))
    if not inputs:
        print(f"[info] No clips found in {in_dir}")
        return

    for clip in inputs:
        print(f"\n=== Designing {clip.name} ===")

        # Decide subtitles path
        srt: Optional[Path] = None
        if args.subs_mode == "file" and args.subs_file:
            srt = Path(args.subs_file) if Path(args.subs_file).exists() else None
            if srt is None:
                print(f"[warn] --subs_file not found; skipping subs for this run.")
        elif args.subs_mode == "auto":
            # Prefer SRT next to the clip; otherwise look in subs_dir
            srt1 = clip.with_suffix(".srt")
            srt2 = Path(args.subs_dir) / (clip.stem + ".srt")
            srt = srt1 if srt1.exists() else (srt2 if srt2.exists() else None)

        # Smart crop (pyannote) or fallback to center crop
        crop_box: Optional[Tuple[int, int, int, int]] = None

        if args.disable_smart_crop:
            print("[info] Smart crop disabled; using center 9:16 crop.")
        else:
            try:
                if args.pyannote_token:
                    crops = resize(
                        video_file_path=str(clip),
                        pyannote_auth_token=args.pyannote_token,
                        aspect_ratio=(9, 16)
                    )
                    crop_box = pick_primary_crop(crops) or None

                    # NEW: Expand the crop box if detected
                    if crop_box and args.crop_expansion != 1.0:
                        video_w, video_h = get_video_dimensions(clip)
                        original_box = crop_box
                        crop_box = expand_crop_box(crop_box, video_w, video_h, args.crop_expansion)
                        print(f"[info] Expanded crop from {original_box} to {crop_box} (factor={args.crop_expansion})")
                else:
                    print("[info] PYANNOTE token missing; using center 9:16 crop.")
            except Exception as e:
                print(f"[warn] resize() failed; using center crop. Details: {e}")

        # Destination
        dst = out_dir / (clip.stem.replace("_subtitled", "") + "_vertical.mp4")

        # Render
        ff_design(
            src=clip,
            dst=dst,
            overlay_png=template,
            crop_box=crop_box,
            out_w=args.width,
            out_h=args.height,
            srt_path=srt
        )

    print("\n✅ All clips designed.")


if __name__ == "__main__":
    main()
