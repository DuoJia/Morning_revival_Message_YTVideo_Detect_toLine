import os
import sys
import json
import time
import requests
import feedparser
import gspread
import yt_dlp
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

# --- Configuration ---
CHANNEL_IDS_RAW = os.getenv("YOUTUBE_CHANNEL_ID", "")
CHANNEL_IDS = [x.strip() for x in CHANNEL_IDS_RAW.split(",") if x.strip()]
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINE_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# 新增: 讀取 Cookies Secret
COOKIES_CONTENT = os.getenv("YOUTUBE_COOKIES")

try:
    key_str = os.getenv("GCP_SA_KEY")
    GCP_SA_KEY = json.loads(key_str) if key_str else None
except Exception as e:
    GCP_SA_KEY = None

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

SYSTEM_PROMPT = """
你是一位精通聖經與教會信息的助理。你將會收到一段教會聚會的錄音檔。
請仔細聆聽內容並進行分析（若音質不佳請盡量辨識）。
請給我最新信息的重點，劉奎元和李俊輝弟兄分享的重點，及能夠幫助聖徒進入經歷分享的突破點，
對應的經文請附在相關的段落，並列出經文本文。以及可供反思的三個問題。
格式要求：使用清晰的 Markdown 標題與條列式。
"""

def get_latest_video(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        latest = feed.entries[0]
        return {
            "id": latest.yt_videoid,
            "title": latest.title,
            "link": latest.link,
            "channel_title": feed.feed.title
        }
    except: return None

def check_if_processed(video_id):
    if not GCP_SA_KEY or not SHEET_ID: return False, None
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SA_KEY, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        return video_id in sheet.col_values(1), sheet
    except: return False, None

def download_audio(video_link, output_filename="temp_audio"):
    """使用 yt-dlp 下載音訊 (含 Cookies 修復)"""
    print(f"   Downloading audio from {video_link}...")
    
    # 1. 建立暫存 Cookies 檔案
    cookie_file = "cookies.txt"
    if COOKIES_CONTENT:
        with open(cookie_file, "w") as f:
            f.write(COOKIES_CONTENT)
    else:
        print("⚠️ Warning: No YOUTUBE_COOKIES found in Secrets. Download might fail.")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '32', 
        }],
        'outtmpl': output_filename,
        'quiet': True,
        # 關鍵修正: 告訴 yt-dlp 使用這個 Cookies 檔案
        'cookiefile': cookie_file if COOKIES_CONTENT else None,
        # 額外修正: 模擬瀏覽器 User Agent，降低被擋機率
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_link])
        
        final_file = f"{output_filename}.mp3"
        
        # 下載完後刪除 cookies 檔案，保持環境乾淨
        if os.path.exists(cookie_file):
            os.remove(cookie_file)
            
        if os.path.exists(final_file):
            return final_file
        return None
    except Exception as e:
        print(f"   Download failed: {e}")
        # 失敗也要記得刪除 cookies
        if os.path.exists(cookie_file):
            os.remove(cookie_file)
        return None

def analyze_audio_with_gemini(audio_path):
    genai.configure(api_key=GEMINI_KEY)
    
    print("   Uploading to Gemini...")
    audio_file = genai.upload_file(path=audio_path)
    
    while audio_file.state.name == "PROCESSING":
        print("   Processing audio file...")
        time.sleep(2)
        audio_file = genai.get_file(audio_file.name)
        
    if audio_file.state.name == "FAILED":
        raise ValueError("Audio processing failed in Gemini.")

    print("   Generating content...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([SYSTEM_PROMPT, audio_file])
    
    return response.text

def send_line_message(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message[:4000]}]}
    requests.post(url, headers=headers, data=json.dumps(payload))

def process_channel(channel_id):
    print(f"\n--- Processing {channel_id} ---")
    video = get_latest_video(channel_id)
    if not video: return

    print(f"Found: [{video['channel_title']}] {video['title']}")
    
    is_processed, sheet = check_if_processed(video['id'])
    if is_processed:
        print(">> Skipped (Processed)")
        return

    # --- 聽覺分析流程 ---
    audio_file = download_audio(video['link'])
    
    if not audio_file:
        print(">> Audio download failed. Skipping.")
        return

    try:
        summary = analyze_audio_with_gemini(audio_file)
        
        final_msg = f"【{video['channel_title']} (聽覺分析)】\n{video['title']}\n{video['link']}\n\n{summary}"
        send_line_message(final_msg)
        
        if sheet:
            sheet.append_row([video['id'], video['title'], "Processed (Audio)"])
            print(">> Done.")
            
    except Exception as e:
        print(f">> Analysis Error: {e}")
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)

def main():
    print(f"=== Audio Analysis Job Start ===")
    for cid in CHANNEL_IDS:
        try:
            process_channel(cid)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
