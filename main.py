import sys
import subprocess
import os

print("="*40)
print("🔍 系統環境診斷模式 (SYSTEM DIAGNOSTIC)")
print("="*40)

# 1. 強制檢查 PIP 安裝的真實版本
print("\n[1] 檢查 PIP 清單 (pip list):")
subprocess.check_call([sys.executable, '-m', 'pip', 'list'])

# 2. 深入檢查 youtube_transcript_api
print("\n[2] 檢查套件本體:")
try:
    import youtube_transcript_api
    from youtube_transcript_api import YouTubeTranscriptApi
    
    # 印出檔案位置 (檢查是否被奇怪的路徑蓋台)
    print(f"📍 檔案位置 (File): {youtube_transcript_api.__file__}")
    
    # 印出版本號 (如果有)
    try:
        print(f"🔢 套件版本 (Version): {youtube_transcript_api.__version__}")
    except:
        print("🔢 套件版本: 無法讀取 (No __version__ attribute)")
        
    # 印出所有功能 (Attributes)
    print(f"\n[3] YouTubeTranscriptApi 類別內的所有功能:")
    attrs = dir(YouTubeTranscriptApi)
    print(attrs)
    
    if 'get_transcript' in attrs:
        print("\n✅ 成功找到: 'get_transcript' 功能存在！")
    else:
        print("\n❌ 嚴重錯誤: 找不到 'get_transcript'。安裝的版本可能極舊或損毀。")

except ImportError as e:
    print(f"❌ Import 失敗: {e}")
except Exception as e:
    print(f"❌ 發生未預期錯誤: {e}")

print("="*40)
print("診斷結束")
print("="*40)
