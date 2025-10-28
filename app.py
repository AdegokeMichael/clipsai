#!/usr/bin/env python3
"""
Flask API Wrapper for ClipsAI Video Processing Pipeline
Integrates with n8n workflow automation
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for n8n requests

# ========= Configuration =========
PROJECT_DIR = Path("/home/michael_adegoke/clipsai")
BASE_DIR = Path("/home/michael_adegoke")
VIDEOS_DIR = BASE_DIR / "videos"
CLIPS_DIR = BASE_DIR / "clips"
SUBTITLED_DIR = BASE_DIR / "subtitled"
DESIGNED_DIR = BASE_DIR / "designed"

# Ensure directories exist
for dir_path in [VIDEOS_DIR, CLIPS_DIR, SUBTITLED_DIR, DESIGNED_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Environment variables
PYANNOTE_TOKEN = os.environ.get("PYANNOTE_AUTH_TOKEN", "")
COOKIES_PATH = os.environ.get("CLIPSAI_COOKIES", str(BASE_DIR / "cookies.txt"))


# ========= Helper Functions =========
def run_script(script_name: str, args: List[str] = None, input_data: str = None) -> Dict:
    """Execute a Python script and return results"""
    try:
        script_path = PROJECT_DIR / script_name
        cmd = ["python3", str(script_path)]
        if args:
            cmd.extend(args)
        
        logger.info(f"Executing: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        logger.error(f"Error executing {script_name}: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def get_file_info(file_path: Path) -> Dict:
    """Get file metadata"""
    if not file_path.exists():
        return None
    
    return {
        "filename": file_path.name,
        "path": str(file_path),
        "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
        "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
    }


def list_directory_files(directory: Path, pattern: str = "*") -> List[Dict]:
    """List files in directory with metadata"""
    files = []
    for file_path in sorted(directory.glob(pattern)):
        if file_path.is_file():
            files.append(get_file_info(file_path))
    return files


# ========= API Endpoints =========

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "directories": {
            "videos": str(VIDEOS_DIR),
            "clips": str(CLIPS_DIR),
            "subtitled": str(SUBTITLED_DIR),
            "designed": str(DESIGNED_DIR)
        },
        "pyannote_configured": bool(PYANNOTE_TOKEN)
    })


@app.route('/process-video', methods=['POST'])
def process_video():
    """
    Step 1: Download YouTube video and create clips using quicktest.py
    
    Request body:
    {
        "url": "https://youtube.com/watch?v=...",
        "video_id": "unique_identifier" (optional)
    }
    """
    try:
        data = request.json
        video_url = data.get('url')
        video_id = data.get('video_id', 'default')
        
        if not video_url:
            return jsonify({"error": "Missing 'url' parameter"}), 400
        
        logger.info(f"Processing video: {video_url}")
        
        # Clean up previous clips
        for old_clip in CLIPS_DIR.glob("clip_*.mp4"):
            old_clip.unlink()
        
        # Run quicktest.py with video URL as input
        result = run_script("quicktest.py", input_data=f"{video_url}\n")
        
        if not result["success"]:
            return jsonify({
                "error": "Video processing failed",
                "details": result["stderr"]
            }), 500
        
        # Get generated clips
        clips = list_directory_files(CLIPS_DIR, "clip_*.mp4")
        
        # Get downloaded video info
        downloaded_video = list(VIDEOS_DIR.glob("input.*"))
        video_info = get_file_info(downloaded_video[0]) if downloaded_video else None
        
        return jsonify({
            "status": "success",
            "video_id": video_id,
            "source_video": video_info,
            "clips_count": len(clips),
            "clips": clips,
            "message": f"Generated {len(clips)} clips from video"
        })
        
    except Exception as e:
        logger.error(f"Error in process_video: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/add-subtitles', methods=['POST'])
def add_subtitles():
    """
    Step 2: Generate and burn subtitles using subtitles.py
    
    Request body:
    {
        "video_id": "unique_identifier" (optional)
    }
    """
    try:
        data = request.json or {}
        video_id = data.get('video_id', 'default')
        
        logger.info("Adding subtitles to clips...")
        
        # Clean up previous subtitled clips
        for old_sub in SUBTITLED_DIR.glob("*.mp4"):
            old_sub.unlink()
        for old_srt in SUBTITLED_DIR.glob("*.srt"):
            old_srt.unlink()
        
        # Run subtitles.py
        result = run_script("subtitles.py")
        
        if not result["success"]:
            return jsonify({
                "error": "Subtitle generation failed",
                "details": result["stderr"]
            }), 500
        
        # Get subtitled clips
        subtitled_clips = list_directory_files(SUBTITLED_DIR, "clip_*_subtitled.mp4")
        srt_files = list_directory_files(SUBTITLED_DIR, "*.srt")
        
        return jsonify({
            "status": "success",
            "video_id": video_id,
            "subtitled_clips_count": len(subtitled_clips),
            "subtitled_clips": subtitled_clips,
            "srt_files_count": len(srt_files),
            "srt_files": srt_files,
            "message": f"Added subtitles to {len(subtitled_clips)} clips"
        })
        
    except Exception as e:
        logger.error(f"Error in add_subtitles: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/apply-design', methods=['POST'])
def apply_design():
    """
    Step 3: Apply 9:16 vertical design with template using design.py
    
    Request body:
    {
        "video_id": "unique_identifier" (optional),
        "crop_expansion": 3.0 (optional, default: 3.0),
        "disable_smart_crop": false (optional, default: false),
        "use_subtitles": true (optional, default: true)
    }
    """
    try:
        data = request.json or {}
        video_id = data.get('video_id', 'default')
        crop_expansion = data.get('crop_expansion', 3.0)
        disable_smart_crop = data.get('disable_smart_crop', False)
        use_subtitles = data.get('use_subtitles', True)
        
        logger.info("Applying vertical design to clips...")
        
        # Clean up previous designed clips
        for old_design in DESIGNED_DIR.glob("*.mp4"):
            old_design.unlink()
        
        # Build command arguments
        args = [
            "--input_dir", str(CLIPS_DIR),
            "--output_dir", str(DESIGNED_DIR),
            "--crop_expansion", str(crop_expansion),
            "--pyannote_token", PYANNOTE_TOKEN
        ]
        
        if disable_smart_crop:
            args.append("--disable_smart_crop")
        
        if use_subtitles:
            args.extend(["--subs_mode", "auto"])
            args.extend(["--subs_dir", str(SUBTITLED_DIR)])
        else:
            args.extend(["--subs_mode", "off"])
        
        # Run design.py
        result = run_script("design.py", args=args)
        
        if not result["success"]:
            return jsonify({
                "error": "Design application failed",
                "details": result["stderr"]
            }), 500
        
        # Get designed clips
        designed_clips = list_directory_files(DESIGNED_DIR, "*_vertical.mp4")
        
        return jsonify({
            "status": "success",
            "video_id": video_id,
            "designed_clips_count": len(designed_clips),
            "designed_clips": designed_clips,
            "settings": {
                "crop_expansion": crop_expansion,
                "smart_crop_enabled": not disable_smart_crop,
                "subtitles_enabled": use_subtitles
            },
            "message": f"Applied design to {len(designed_clips)} clips"
        })
        
    except Exception as e:
        logger.error(f"Error in apply_design: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/process-complete-pipeline', methods=['POST'])
def process_complete_pipeline():
    """
    All-in-one endpoint: Download → Clip → Subtitle → Design
    
    Request body:
    {
        "url": "https://youtube.com/watch?v=...",
        "video_id": "unique_identifier" (optional),
        "crop_expansion": 3.0 (optional),
        "disable_smart_crop": false (optional),
        "use_subtitles": true (optional)
    }
    """
    try:
        data = request.json
        video_url = data.get('url')
        
        if not video_url:
            return jsonify({"error": "Missing 'url' parameter"}), 400
        
        results = {}
        
        # Step 1: Process video
        logger.info("Step 1/3: Processing video and creating clips...")
        step1 = process_video()
        results['step1_clips'] = step1.get_json()
        
        if step1.status_code != 200:
            return step1
        
        # Step 2: Add subtitles
        logger.info("Step 2/3: Adding subtitles...")
        step2 = add_subtitles()
        results['step2_subtitles'] = step2.get_json()
        
        if step2.status_code != 200:
            return step2
        
        # Step 3: Apply design
        logger.info("Step 3/3: Applying vertical design...")
        design_data = {
            "video_id": data.get('video_id'),
            "crop_expansion": data.get('crop_expansion', 3.0),
            "disable_smart_crop": data.get('disable_smart_crop', False),
            "use_subtitles": data.get('use_subtitles', True)
        }
        
        # Temporarily override request.json for apply_design
        original_json = request.json
        request.json = design_data
        step3 = apply_design()
        request.json = original_json
        
        results['step3_design'] = step3.get_json()
        
        if step3.status_code != 200:
            return step3
        
        return jsonify({
            "status": "success",
            "message": "Complete pipeline executed successfully",
            "summary": {
                "clips_generated": results['step1_clips']['clips_count'],
                "subtitles_added": results['step2_subtitles']['subtitled_clips_count'],
                "designs_created": results['step3_design']['designed_clips_count']
            },
            "details": results
        })
        
    except Exception as e:
        logger.error(f"Error in complete pipeline: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/download-file/<path:filename>', methods=['GET'])
def download_file(filename):
    """
    Download a processed file
    
    Query params:
    - type: clips|subtitled|designed (default: designed)
    """
    try:
        file_type = request.args.get('type', 'designed')
        
        directory_map = {
            'clips': CLIPS_DIR,
            'subtitled': SUBTITLED_DIR,
            'designed': DESIGNED_DIR,
            'videos': VIDEOS_DIR
        }
        
        directory = directory_map.get(file_type, DESIGNED_DIR)
        file_path = directory / filename
        
        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/list-files', methods=['GET'])
def list_files():
    """
    List all files in processing directories
    
    Query params:
    - type: clips|subtitled|designed|all (default: all)
    """
    try:
        file_type = request.args.get('type', 'all')
        
        result = {}
        
        if file_type in ['clips', 'all']:
            result['clips'] = list_directory_files(CLIPS_DIR, "clip_*.mp4")
        
        if file_type in ['subtitled', 'all']:
            result['subtitled'] = list_directory_files(SUBTITLED_DIR, "*_subtitled.mp4")
            result['srt_files'] = list_directory_files(SUBTITLED_DIR, "*.srt")
        
        if file_type in ['designed', 'all']:
            result['designed'] = list_directory_files(DESIGNED_DIR, "*_vertical.mp4")
        
        if file_type in ['videos', 'all']:
            result['source_videos'] = list_directory_files(VIDEOS_DIR)
        
        return jsonify({
            "status": "success",
            "files": result
        })
        
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/cleanup', methods=['POST'])
def cleanup():
    """
    Clean up all processed files
    
    Request body:
    {
        "directories": ["clips", "subtitled", "designed", "videos"] (optional, default: all)
    }
    """
    try:
        data = request.json or {}
        directories = data.get('directories', ['clips', 'subtitled', 'designed', 'videos'])
        
        cleaned = {}
        
        directory_map = {
            'clips': CLIPS_DIR,
            'subtitled': SUBTITLED_DIR,
            'designed': DESIGNED_DIR,
            'videos': VIDEOS_DIR
        }
        
        for dir_name in directories:
            if dir_name in directory_map:
                directory = directory_map[dir_name]
                files_removed = 0
                
                for file_path in directory.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()
                        files_removed += 1
                
                cleaned[dir_name] = files_removed
        
        return jsonify({
            "status": "success",
            "cleaned": cleaned,
            "message": f"Cleaned {sum(cleaned.values())} files"
        })
        
    except Exception as e:
        logger.error(f"Error in cleanup: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ========= Error Handlers =========
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


# ========= Main =========
if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=5000, debug=True)
    
    # For production, use:
    # gunicorn -w 4 -b 0.0.0.0:5000 --timeout 600 api:app
