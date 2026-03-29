import os
import requests
import subprocess
import assemblyai as aai
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import shutil

load_dotenv()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

app = FastAPI()

DIRS =["input", "clips", "audio", "subtitles", "output"]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

app.mount("/output", StaticFiles(directory="output"), name="output")
templates = Jinja2Templates(directory="templates")

def generate_subtitles(audio_path: str):
    transcript = aai.Transcriber().transcribe(audio_path)
    srt_path = "subtitles/subs.srt"
    with open(srt_path, "w") as f:
        f.write(transcript.export_subtitles_srt())
    return srt_path, transcript.audio_duration

def download_pexels_videos(queries: list):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_clips =[]
    for i, query in enumerate(queries):
        url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"
        res = requests.get(url, headers=headers).json()
        if "videos" in res and res["videos"]:
            video_url = max(res["videos"][0]["video_files"], key=lambda x: x.get('width', 0))["link"]
            clip_path = f"clips/clip_{i}.mp4"
            with open(clip_path, 'wb') as f:
                f.write(requests.get(video_url).content)
            downloaded_clips.append(clip_path)
    return downloaded_clips

def process_and_merge_videos(clips: list, audio_path: str, srt_path: str, duration: float):
    time_per_clip = duration / len(clips)
    processed_clips =[]
    for i, clip in enumerate(clips):
        out = f"clips/proc_{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", clip, "-t", str(time_per_clip), "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1", "-c:v", "libx264", "-preset", "fast", "-an", out])
        processed_clips.append(out)
        
    with open("clips/concat.txt", "w") as f:
        for pc in processed_clips:
            f.write(f"file '{os.path.abspath(pc)}'\n")
            
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips/concat.txt", "-c", "copy", "clips/merged.mp4"])
    srt_filter = f"subtitles={srt_path}:force_style='Fontname=Arial,Fontsize=22,PrimaryColour=&H00FFFF,Outline=3,Alignment=2,MarginV=90,Bold=-1'"
    subprocess.run(["ffmpeg", "-y", "-i", "clips/merged.mp4", "-i", audio_path, "-vf", srt_filter, "-c:v", "libx264", "-c:a", "aac", "-shortest", "output/final.mp4"])
    return "/output/final.mp4"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/generate-video")
async def generate_video(keywords: str = Form(...), audio_file: UploadFile = File(...)):
    try:
        audio_path = f"audio/{audio_file.filename}"
        with open(audio_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)
            
        srt_path, duration = generate_subtitles(audio_path)
        user_keywords = [k.strip() for k in keywords.split(",") if k.strip()] or["study", "books", "hospital"]
        num_scenes = max(4, int(duration // 8))
        
        final_queries = [user_keywords[i % len(user_keywords)] for i in range(num_scenes)]
        clips = download_pexels_videos(final_queries)
        
        if not clips: return {"error": "No videos found for these words."}
        video_url = process_and_merge_videos(clips, audio_path, srt_path, duration)
        
        return {"status": "success", "video_url": video_url}
    except Exception as e:
        return {"error": str(e)}
