import os
import sys
import json
import requests
import feedparser
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai

# --- Configuration (Load from Environment Variables) ---
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID") # 目標頻道 ID
SHEET_ID = os.getenv("GOOGLE_SHEET_ID") # 記錄歷史的 Sheet ID
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINE_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
GCP_SA_KEY = json.loads(os.getenv("GCP_SA_KEY")) # Service Account JSON

# --- Constants ---
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# --- Prompt Settings ---
SYSTEM_PROMPT = """
你是一位精通聖經與教會信息的助理。請針對提供的影片逐字稿進行分析。
請給我最新信息的重點，劉奎元和李俊輝弟兄分享的重點，及能夠幫助聖徒進入經歷分享的突破點，
對應的經文請附在相關的段落，並列出經文本文。以及可供反思的三個問題。
格式要求：使用清晰的 Markdown 標題與條列式。
"""

def get_latest_video():
    """透過 RSS 獲取最新影片資訊 (最省資源的方式)"""
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        return None
    latest = feed.entries[0]
    return {
        "id": latest.yt_videoid,
        "title": latest.title,
        "link": latest.link
    }

def check_if_processed(video_id):
    """檢查 Google Sheet 是否已有該影片 ID"""
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SA_KEY, SCOPE)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    
    # 假設 ID 存第一欄，簡單讀取所有 ID (量大時建議優化，但在 Side Project 足夠)
    ids = sheet.col_values(1) 
    return video_id in ids, sheet

def get_transcript(video_id):
    """獲取影片逐字稿"""
    try:
        # 嘗試獲取中文或自動生成的字幕
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-Hant', 'zh', 'en'])
        full_text = " ".join([t['text'] for t in transcript_list])
        return full_text
    except Exception as e:
        print(f"Error fetching transcript: {e}")
        return None

def analyze_with_gemini(text):
    """使用 Gemini 分析內容"""
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\n以下是逐字稿內容：\n{text}")
    return response.text

def send_line_message(message):
    """發送 LINE 訊息 (處理長度限制)"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    
    # LINE 單次限制 5000 字，這裡做簡單截斷或分段
    # 為了簡潔，這裡示範發送前 2000 字，實際應用建議寫個 loop 分段發送
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message[:2000]}] 
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        print(f"Failed to send LINE: {response.text}")

def main():
    try:
        print("1. Checking for new video...")
        video = get_latest_video()
        if not video:
            print("No videos found.")
            return

        print(f"Found video: {video['title']} ({video['id']})")

        is_processed, sheet = check_if_processed(video['id'])
        if is_processed:
            print("Video already processed. Skipping.")
            return

        print("2. New video detected. Fetching transcript...")
        transcript = get_transcript(video['id'])
        
        if not transcript:
            print("No transcript available. Cannot analyze.")
            # 視情況決定是否要標記為已處理，避免卡住
            return 

        print("3. Analyzing with Gemini...")
        summary = analyze_with_gemini(transcript)
        
        # 加上影片標題與連結
        final_msg = f"【新影片分析】{video['title']}\n{video['link']}\n\n{summary}"

        print("4. Sending to LINE...")
        send_line_message(final_msg)

        print("5. Updating Database...")
        sheet.append_row([video['id'], video['title'], "Processed"])
        print("Success!")

    except Exception as e:
        print(f"Critical Error: {e}")
        # 在這裡也可以加一個 send_line_message 通知管理員腳本掛了
        sys.exit(1)

if __name__ == "__main__":
    main()
