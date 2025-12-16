import os
import sys
import json
import requests
import feedparser
import gspread
from oauth2client.service_account import ServiceAccountCredentials
# 修改點 1: 改用最安全的引入方式，避免命名衝突
import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai

# --- Configuration ---
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINE_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")
GCP_SA_KEY = json.loads(os.getenv("GCP_SA_KEY"))

# --- Constants ---
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

SYSTEM_PROMPT = """
你是一位精通聖經與教會信息的助理。請針對提供的影片逐字稿進行分析。
請給我最新信息的重點，劉奎元和李俊輝弟兄分享的重點，及能夠幫助聖徒進入經歷分享的突破點，
對應的經文請附在相關的段落，並列出經文本文。以及可供反思的三個問題。
格式要求：使用清晰的 Markdown 標題與條列式。
"""

def get_latest_video():
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
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SA_KEY, SCOPE)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    ids = sheet.col_values(1)
    return video_id in ids, sheet

def get_transcript(video_id):
    """獲取影片逐字稿 (修正版)"""
    try:
        # 修改點 2: 直接呼叫，並嘗試多種語言代碼
        print(f"DEBUG: Attempting to fetch transcript for {video_id}...")
        
        # 這裡列出所有可能的中文代碼
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id, 
            languages=['zh-TW', 'zh-Hant', 'zh', 'en']
        )
        
        full_text = " ".join([t['text'] for t in transcript_list])
        print(f"DEBUG: Transcript fetched. Length: {len(full_text)} chars")
        return full_text

    except Exception as e:
        # 修改點 3: 印出更詳細的錯誤，方便我們看 Log
        print(f"Error fetching transcript details: {e}")
        # 有時候是因為影片真的沒有字幕 (例如直播剛結束還在處理中)
        return None

def analyze_with_gemini(text):
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\n以下是逐字稿內容：\n{text}")
    return response.text

def send_line_message(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message[:2000]}] 
    }
    requests.post(url, headers=headers, data=json.dumps(payload))

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
            print("❌ No transcript available. Stopping here.")
            # 這裡我們不寫入資料庫，這樣下次排程跑的時候還會再試一次
            # 因為有時候 YouTube 生成字幕需要幾個小時
            return 

        print("3. Analyzing with Gemini...")
        summary = analyze_with_gemini(transcript)
        
        final_msg = f"【新影片分析】{video['title']}\n{video['link']}\n\n{summary}"

        print("4. Sending to LINE...")
        send_line_message(final_msg)

        print("5. Updating Database...")
        sheet.append_row([video['id'], video['title'], "Processed"])
        print("Success!")

    except Exception as e:
        print(f"Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
