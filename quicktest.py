#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from clipsai import ClipFinder, Transcriber

# ========= Paths (portable) =========
PROJECT_DIR = Path(__file__).resolve().parent                 # /home/.../clipsai
MEDIA_DIR   = Path(os.getenv("CLIPSAI_MEDIA_DIR", PROJECT_DIR.parent))  # default: /home/.../
VIDEOS_DIR  = MEDIA_DIR / "videos"
CLIPS_DIR   = MEDIA_DIR / "clips"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

# Optional cookies (e.g., for age/region gating)
COOKIES_PATH = os.getenv("CLIPSAI_COOKIES", str(MEDIA_DIR / "cookies.txt"))

# ========= Input =========
video_url = input("Enter YouTube URL: ").strip()
if not video_url:
    raise SystemExit("No URL provided.")

# ========= Step 1: Download source video =========
print(" Downloading video...")
output_template = str(VIDEOS_DIR / "input.%(ext)s")

yt_cmd = ["yt-dlp", "-o", output_template, video_url]
if Path(COOKIES_PATH).exists():
    yt_cmd[1:1] = ["--cookies", COOKIES_PATH]  # insert after binary

subprocess.run(yt_cmd, check=True)

downloaded_files = sorted(VIDEOS_DIR.glob("input.*"))
if not downloaded_files:
    raise FileNotFoundError(" No video was downloaded!")
input_video = str(downloaded_files[0])
print(f" Video downloaded to: {input_video}")

# ========= Step 2: Transcribe =========
print(" Transcribing...")
transcriber = Transcriber()  # uses clipsai defaults
transcription = transcriber.transcribe(audio_file_path=input_video)

# ========= Step 3: Find clips =========
print(" Finding interesting clips...")
clipfinder = ClipFinder()
clips = clipfinder.find_clips(transcription=transcription)
if not clips:
    raise SystemExit("No clips were found.")

# ========= Step 4: Save clips (stream copy) =========
for idx, clip in enumerate(clips, start=1):
    start = clip.start_time
    end = clip.end_time
    duration = end - start
    output_file = CLIPS_DIR / f"clip_{idx}.mp4"

    print(f" Saving clip {idx}: {start:.2f} → {end:.2f} as {output_file}")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_video,
        "-ss", str(start),
        "-t", str(duration),
        "-c", "copy",
        str(output_file)
    ], check=True)

print("All clips saved in:", CLIPS_DIR)
