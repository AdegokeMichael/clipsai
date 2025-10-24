import os
import subprocess
from pathlib import Path
import whisper

# -------- CONFIG --------
base_dir = Path("/home/michael_adegoke")
clips_dir = base_dir / "clips"
subs_dir = base_dir / "subtitled"
subs_dir.mkdir(parents=True, exist_ok=True)

# Load Whisper (tiny/medium/large available)
print("📝 Loading Whisper model...")
model = whisper.load_model("small")

# -------- Process all clips --------
for clip_file in clips_dir.glob("clip_*.mp4"):
    print(f"🎬 Processing {clip_file.name}...")

    # Step 1: Transcribe
    result = model.transcribe(str(clip_file), verbose=False)
    srt_path = subs_dir / (clip_file.stem + ".srt")

    # Step 2: Save subtitles in SRT format
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(result["segments"], start=1):
            start = segment["start"]
            end = segment["end"]
            text = segment["text"].strip()

            # Convert to SRT timestamp format
            def format_time(t):
                hrs = int(t // 3600)
                mins = int((t % 3600) // 60)
                secs = int(t % 60)
                ms = int((t * 1000) % 1000)
                return f"{hrs:02}:{mins:02}:{secs:02},{ms:03}"

            f.write(f"{i}\n{format_time(start)} --> {format_time(end)}\n{text}\n\n")

    print(f"✅ Subtitles saved to {srt_path}")

    # Step 3: Burn subtitles into video
    output_file = subs_dir / (clip_file.stem + "_subtitled.mp4")
    subprocess.run([
        "ffmpeg",
        "-i", str(clip_file),
        "-vf", f"subtitles={srt_path}",
        "-c:a", "copy",
        str(output_file)
    ], check=True)

    print(f"✅ Subtitled video saved to {output_file}")

print("🎉 All clips processed with subtitles!")