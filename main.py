import os
import sys
import json
import requests
import feedparser
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai

# --- Configuration ---
# 1. 讀取並分割頻道 ID (支援多頻道，以逗號分隔)
CHANNEL_IDS_RAW = os.getenv("YOUTUBE_CHANNEL_ID", "")
CHANNEL_IDS = [x.strip() for x in CHANNEL_IDS_RAW.split(",") if x.strip()]

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINE_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

try:
    key_str = os.getenv("GCP_SA_KEY")
    GCP_SA_KEY = json.loads(key_str) if key_str else None
except Exception as e:
    print(f"Error parsing GCP_SA_KEY: {e}")
    GCP_SA_KEY = None

# --- Constants ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 注意：因為有多個頻道，Prompt 可能需要通用化，或者針對不同頻道做判斷(目前維持統一)
SYSTEM_PROMPT = """
你是一位精通聖經與教會信息的助理。請針對提供的影片逐字稿進行分析。
請給我最新信息的重點，劉奎元和李俊輝弟兄分享的重點，及能夠幫助聖徒進入經歷分享的突破點，
對應的經文請附在相關的段落，並列出經文本文。以及可供反思的三個問題。
格式要求：使用清晰的 Markdown 標題與條列式。
"""

def get_latest_video(channel_id):
    """獲取指定頻道的最新影片"""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return None
        latest = feed.entries[0]
        return {
            "id": latest.yt_videoid,
            "title": latest.title,
            "link": latest.link,
            "channel_title": feed.feed.title # 抓取頻道名稱方便辨識
        }
    except Exception as e:
        print(f"Error parsing RSS for {channel_id}: {e}")
        return None

def check_if_processed(video_id):
    """檢查是否已處理"""
    if not GCP_SA_KEY or not SHEET_ID:
        return False, None
    
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SA_KEY, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        ids = sheet.col_values(1)
        return video_id in ids, sheet
    except Exception as e:
        print(f"Database Error: {e}")
        return False, None

def get_transcript(video_id):
    """獲取字幕"""
    try:
        print(f"   Fetching transcript for {video_id}...")
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id, 
            languages=['zh-TW', 'zh-Hant', 'zh', 'en']
        )
        full_text = " ".join([t['text'] for t in transcript_list])
        return full_text
    except Exception as e:
        print(f"   ℹ️ Transcript not available: {e}")
        return None

def analyze_with_gemini(text):
    """Gemini 分析"""
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\n以下是逐字稿內容：\n{text}")
    return response.text

def send_line_message(message):
    """發送 LINE 通知"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message[:4000]}] 
    }
    requests.post(url, headers=headers, data=json.dumps(payload))

def process_channel(channel_id):
    """處理單一頻道的邏輯"""
    print(f"\n--- Processing Channel ID: {channel_id} ---")
    
    # 1. 抓取該頻道最新影片
    video = get_latest_video(channel_id)
    if not video:
        print(f"No videos found for channel {channel_id}.")
        return

    print(f"Found: [{video['channel_title']}] {video['title']} ({video['id']})")

    # 2. 檢查資料庫
    is_processed, sheet = check_if_processed(video['id'])
    if is_processed:
        print(">> Video already processed. Skipping.")
        return

    # 3. 獲取字幕
    transcript = get_transcript(video['id'])
    if not transcript:
        print(">> No transcript available. Skipping analysis.")
        return 

    # 4. Gemini 分析
    print(">> Analyzing with Gemini...")
    try:
        summary = analyze_with_gemini(transcript)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return

    # 5. 發送通知 (標題加上頻道名稱)
    final_msg = f"【{video['channel_title']}】\n{video['title']}\n{video['link']}\n\n{summary}"
    print(">> Sending to LINE...")
    send_line_message(final_msg)

    # 6. 寫入資料庫
    if sheet:
        print(">> Updating Google Sheet...")
        sheet.append_row([video['id'], video['title'], "Processed"])
        print(">> Done.")

def main():
    print(f"=== Start Job: Monitoring {len(CHANNEL_IDS)} Channels ===")
    
    if not CHANNEL_IDS:
        print("Error: No CHANNEL_IDS found in environment variables.")
        return

    # 迴圈：一個一個頻道輪流檢查
    for cid in CHANNEL_IDS:
        try:
            process_channel(cid)
        except Exception as e:
            print(f"Critical error processing channel {cid}: {e}")
            continue # 確保其中一個頻道掛掉，不會影響下一個頻道
    
    print("\n=== All Jobs Finished ===")

if __name__ == "__main__":
    main()
