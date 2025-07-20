# High-Speed Telegram Download Bot - GitHub Actions Version
import asyncio
import time
import os
import signal
import sys
import aiohttp
from datetime import datetime
import logging
from typing import Optional, Union, List, BinaryIO, DefaultDict, Tuple
import tempfile
import shutil
import concurrent.futures
from pathlib import Path
import inspect
import math
import hashlib
from collections import defaultdict
import threading
import http.server
import socketserver
from urllib.parse import quote

# Fix encoding for Windows GitHub Actions
if os.name == 'nt':  # Windows
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

from pyrogram import Client, filters
from pyrogram.types import Message
import aiofiles

# Configuration - Read from environment variables
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")  
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Validate credentials
if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("[ERROR] Missing credentials! Please check your GitHub secrets.")
    sys.exit(1)

# GitHub Actions paths
DOWNLOAD_PATH = os.path.join(os.getcwd(), "downloads")
TEMP_PATH = os.path.join(os.getcwd(), "temp")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(TEMP_PATH, exist_ok=True)

# Server configuration
SERVER_PORT = 8080
PUBLIC_URL = "http://islands-km.gl.at.ply.gg:46886"

# Configuration
OPTIMIZATION_CONFIG = {
    "workers": 32,
    "ipv6": False,
    "proxy": None,
    "test_mode": False,
    "chunk_size": 2 * 1024 * 1024,
    "max_concurrent_downloads": 5,
    "max_connections_per_download": 20,
    "use_temp_files": True,
    "buffer_size": 16384,
    "max_retries": 5,
    "retry_delay": 1,
    "progress_update_interval": 1.0,
}

# Setup logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Global variables
bot_running = True
active_downloads = {}
transfer_locks = defaultdict(asyncio.Lock)
server_thread = None

class FileServer:
    """HTTP File Server to serve downloaded files"""
    
    def __init__(self, directory, port):
        self.directory = directory
        self.port = port
        self.httpd = None
        
    def start_server(self):
        """Start the HTTP server in a separate thread"""
        os.chdir(self.directory)
        
        class CustomHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Reduce server logs
                
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                super().end_headers()
        
        Handler = CustomHandler
        self.httpd = socketserver.TCPServer(("", self.port), Handler)
        
        print(f"[SERVER] File server started on port {self.port}")
        print(f"[SERVER] Serving files from: {self.directory}")
        print(f"[SERVER] Public URL: {PUBLIC_URL}")
        
        self.httpd.serve_forever()
    
    def stop_server(self):
        """Stop the HTTP server"""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

class AdvancedSpeedTracker:
    def __init__(self):
        self.start_time = None
        self.last_update = None
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed_history = []
        self.last_progress_time = 0
        self.peak_speed = 0

    def start_download(self, total_size):
        self.start_time = time.time()
        self.last_update = self.start_time
        self.total_bytes = total_size
        self.downloaded_bytes = 0
        self.speed_history = []
        self.last_progress_time = 0
        self.peak_speed = 0

    def update_progress(self, current_bytes, total_bytes):
        now = time.time()
        self.downloaded_bytes = current_bytes
        self.total_bytes = total_bytes
        
        if self.last_update:
            time_diff = now - self.last_update
            if time_diff > 0:
                bytes_diff = current_bytes - (self.speed_history[-1][1] if self.speed_history else 0)
                speed = bytes_diff / time_diff
                self.speed_history.append((now, current_bytes, speed))
                
                if speed > self.peak_speed:
                    self.peak_speed = speed
                
                if len(self.speed_history) > 20:
                    self.speed_history = self.speed_history[-20:]

        self.last_update = now

    def get_advanced_stats(self):
        if not self.start_time:
            return None

        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return None

        avg_speed = self.downloaded_bytes / elapsed if elapsed > 0 else 0
        recent_speeds = [s[2] for s in self.speed_history[-3:] if s[2] > 0]
        current_speed = sum(recent_speeds) / len(recent_speeds) if recent_speeds else avg_speed
        smooth_speeds = [s[2] for s in self.speed_history[-10:] if s[2] > 0]
        smooth_speed = sum(smooth_speeds) / len(smooth_speeds) if smooth_speeds else avg_speed
        progress = (self.downloaded_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0
        remaining_bytes = self.total_bytes - self.downloaded_bytes
        eta_seconds = remaining_bytes / smooth_speed if smooth_speed > 0 else 0

        return {
            'elapsed': elapsed,
            'progress': progress,
            'downloaded': self.downloaded_bytes,
            'total': self.total_bytes,
            'avg_speed': avg_speed,
            'current_speed': current_speed,
            'smooth_speed': smooth_speed,
            'peak_speed': self.peak_speed,
            'eta': eta_seconds
        }

def format_bytes(bytes_value):
    """Convert bytes to human readable format"""
    if bytes_value == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} TB"

def format_speed(bytes_per_second):
    """Convert bytes per second to human readable format"""
    return f"{format_bytes(bytes_per_second)}/s"

def format_time(seconds):
    """Convert seconds to human readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"

def generate_download_url(filename):
    """Generate download URL for the file"""
    encoded_filename = quote(filename)
    return f"{PUBLIC_URL}/{encoded_filename}"

# Initialize Pyrogram client
app = Client(
    "speed_optimized_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=OPTIMIZATION_CONFIG["workers"],
    ipv6=OPTIMIZATION_CONFIG["ipv6"],
    proxy=OPTIMIZATION_CONFIG["proxy"],
    test_mode=OPTIMIZATION_CONFIG["test_mode"]
)

download_semaphore = asyncio.Semaphore(OPTIMIZATION_CONFIG["max_concurrent_downloads"])

class OptimizedDownloader:
    def __init__(self, client: Client):
        self.client = client
        self.speed_tracker = AdvancedSpeedTracker()
        self.status_msg = None

    async def download_with_retry(self, message: Message, file_path: str, max_retries: int = 5):
        """Download with retry logic"""
        for attempt in range(max_retries):
            try:
                return await self._download_optimized(message, file_path)
            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(OPTIMIZATION_CONFIG["retry_delay"] * (attempt + 1))
                else:
                    raise e

    async def _download_optimized(self, message: Message, file_path: str):
        """Optimized download method"""
        if OPTIMIZATION_CONFIG["use_temp_files"]:
            temp_file = os.path.join(TEMP_PATH, f"temp_{message.id}_{int(time.time())}")
            try:
                downloaded_file = await self.client.download_media(
                    message,
                    file_name=temp_file,
                    progress=self.progress_callback
                )
                
                if downloaded_file and os.path.exists(downloaded_file):
                    shutil.move(downloaded_file, file_path)
                    return file_path
                else:
                    return None
            finally:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
        else:
            return await self.client.download_media(
                message,
                file_name=file_path,
                progress=self.progress_callback
            )

    async def progress_callback(self, current, total):
        """Progress callback with Telegram updates"""
        self.speed_tracker.update_progress(current, total)
        stats = self.speed_tracker.get_advanced_stats()
        
        if stats and stats['elapsed'] > 0:
            current_time = time.time()
            if current_time - self.speed_tracker.last_progress_time >= OPTIMIZATION_CONFIG["progress_update_interval"]:
                print(f"[DOWNLOAD] {stats['progress']:.1f}% | "
                      f"Speed: {format_speed(stats['current_speed'])} | "
                      f"Peak: {format_speed(stats['peak_speed'])} | "
                      f"Downloaded: {format_bytes(stats['downloaded'])}/{format_bytes(stats['total'])} | "
                      f"ETA: {format_time(stats['eta'])}")
                
                if self.status_msg and current_time - self.speed_tracker.last_progress_time >= 5:
                    try:
                        await self.status_msg.edit_text(
                            f"**Downloading to Server**\n\n"
                            f"**Progress:** {stats['progress']:.1f}%\n"
                            f"**Speed:** {format_speed(stats['current_speed'])}\n"
                            f"**Peak:** {format_speed(stats['peak_speed'])}\n"
                            f"**Downloaded:** {format_bytes(stats['downloaded'])}/{format_bytes(stats['total'])}\n"
                            f"**ETA:** {format_time(stats['eta'])}\n"
                            f"**Status:** Downloading..."
                        )
                    except:
                        pass
                
                self.speed_tracker.last_progress_time = current_time

@app.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_optimized_download(client, message: Message):
    """Handle file download with server integration"""
    async with download_semaphore:
        try:
            user_name = message.from_user.first_name if message.from_user else "Unknown"
            print(f"[BOT] High-speed download started by {user_name}")

            file_obj, file_name, file_size = get_file_info(message)
            if not file_obj:
                await message.reply_text("❌ Unsupported file type")
                return

            print(f"[BOT] File: {file_name}")
            print(f"[BOT] Size: {format_bytes(file_size)}")

            if file_size > 4 * 1024 * 1024 * 1024:  # 4GB
                await message.reply_text("❌ File too large (>4GB)")
                return

            if file_size == 0:
                await message.reply_text("⚠️ Cannot determine file size")
                return

            safe_filename = sanitize_filename(file_name)
            file_path = os.path.join(DOWNLOAD_PATH, safe_filename)

            status_msg = await message.reply_text(
                f"**Download Starting**\n\n"
                f"**File:** {file_name}\n"
                f"**Size:** {format_bytes(file_size)}\n"
                f"**Server:** {PUBLIC_URL}\n"
                f"**Workers:** {OPTIMIZATION_CONFIG['workers']}\n"
                f"**Status:** Initializing..."
            )

            download_id = f"{message.chat.id}_{message.id}"
            active_downloads[download_id] = {
                'start_time': time.time(),
                'file_name': file_name,
                'file_size': file_size
            }

            downloader = OptimizedDownloader(client)
            downloader.status_msg = status_msg
            downloader.speed_tracker.start_download(file_size)

            download_start = time.time()

            try:
                downloaded_file = await downloader.download_with_retry(
                    message,
                    file_path,
                    OPTIMIZATION_CONFIG["max_retries"]
                )

                download_end = time.time()
                download_time = download_end - download_start

                if downloaded_file and os.path.exists(downloaded_file):
                    actual_size = os.path.getsize(downloaded_file)
                    stats = downloader.speed_tracker.get_advanced_stats()
                    
                    download_url = generate_download_url(safe_filename)
                    
                    print(f"[SUCCESS] Download completed!")
                    print(f"[SUCCESS] File: {downloaded_file}")
                    print(f"[SUCCESS] URL: {download_url}")

                    await status_msg.edit_text(
                        f"**Download Complete!**\n\n"
                        f"**File:** {file_name}\n"
                        f"**Size:** {format_bytes(actual_size)}\n"
                        f"**Time:** {format_time(download_time)}\n"
                        f"**Avg Speed:** {format_speed(stats['avg_speed'])}\n"
                        f"**Peak Speed:** {format_speed(stats['peak_speed'])}\n"
                        f"**Server:** Ready\n\n"
                        f"**Download URL:**\n`{download_url}`\n\n"
                        f"Click the URL to download the file!"
                    )
                    
                    await message.reply_text(
                        f"**Direct Download Link:**\n\n{download_url}\n\n"
                        f"**Instructions:**\n"
                        f"• Click the link to download\n"
                        f"• Share this URL with others\n"
                        f"• Link is valid while server is running"
                    )

                else:
                    print(f"[ERROR] Download failed - file not found")
                    await status_msg.edit_text("❌ Download failed")

            except Exception as download_error:
                print(f"[ERROR] Download error: {download_error}")
                await status_msg.edit_text(f"❌ Download failed: {str(download_error)}")

            finally:
                if download_id in active_downloads:
                    del active_downloads[download_id]

        except Exception as e:
            print(f"[ERROR] Error in optimized download: {e}")
            await message.reply_text(f"❌ Error: {str(e)}")

def get_file_info(message: Message):
    """Extract file information from message"""
    if message.document:
        return message.document, message.document.file_name or f"document_{message.id}", message.document.file_size or 0
    elif message.video:
        return message.video, f"video_{message.id}.mp4", message.video.file_size or 0
    elif message.audio:
        return message.audio, message.audio.file_name or f"audio_{message.id}.mp3", message.audio.file_size or 0
    elif message.photo:
        photo = message.photo[-1]
        return photo, f"photo_{message.id}.jpg", photo.file_size or 0
    return None, None, 0

def sanitize_filename(filename: str) -> str:
    """Create a safe filename"""
    safe_name = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    return safe_name if safe_name and safe_name != "." else f"file_{int(time.time())}"

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Start command"""
    await message.reply_text(
        f"**High-Speed Telegram Download Bot**\n\n"
        f"**Server Integration:**\n"
        f"• Files served at: {PUBLIC_URL}\n"
        f"• Port: {SERVER_PORT}\n"
        f"• Auto-generates download URLs\n\n"
        f"**Optimizations Active:**\n"
        f"• {OPTIMIZATION_CONFIG['workers']} worker threads\n"
        f"• {OPTIMIZATION_CONFIG['max_connections_per_download']} parallel connections\n"
        f"• {format_bytes(OPTIMIZATION_CONFIG['chunk_size'])} chunk size\n"
        f"• Advanced retry logic\n"
        f"• Real-time progress updates\n\n"
        f"**Send any file to get download URL!**\n\n"
        f"**Commands:**\n"
        f"/start - Show this message\n"
        f"/status - Check downloads & server\n"
        f"/files - List available files\n"
        f"/clear - Clear downloads\n"
        f"/stop - Stop bot"
    )

@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    """Status command"""
    try:
        files = []
        total_size = 0
        if os.path.exists(DOWNLOAD_PATH):
            for file in os.listdir(DOWNLOAD_PATH):
                file_path = os.path.join(DOWNLOAD_PATH, file)
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    files.append((file, size))
                    total_size += size

        active_count = len(active_downloads)
        status_text = f"**Bot & Server Status**\n\n"
        status_text += f"**File Server:**\n"
        status_text += f"• URL: {PUBLIC_URL}\n"
        status_text += f"• Port: {SERVER_PORT}\n"
        status_text += f"• Status: Running\n\n"
        status_text += f"**Storage:**\n"
        status_text += f"• Files: {len(files)}\n"
        status_text += f"• Total Size: {format_bytes(total_size)}\n"
        status_text += f"• Path: ./downloads/\n\n"
        status_text += f"**Active Downloads:** {active_count}\n"
        status_text += f"**Workers:** {OPTIMIZATION_CONFIG['workers']}\n"

        await message.reply_text(status_text)

    except Exception as e:
        await message.reply_text(f"❌ Error getting status: {str(e)}")

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global bot_running
    print(f"[SIGNAL] Received signal {signum}, stopping bot...")
    bot_running = False

async def main():
    """Main function with server integration"""
    global bot_running, server_thread
    
    print("[STARTUP] Starting High-Speed Telegram Download Bot with File Server...")
    print(f"[STARTUP] Downloads: {DOWNLOAD_PATH}")
    print(f"[STARTUP] Temp: {TEMP_PATH}")
    print(f"[STARTUP] Server: {PUBLIC_URL}")
    print(f"[STARTUP] Port: {SERVER_PORT}")

    # Start file server in background thread
    file_server = FileServer(DOWNLOAD_PATH, SERVER_PORT)
    server_thread = threading.Thread(target=file_server.start_server, daemon=True)
    server_thread.start()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await app.start()
        print("[BOT] Bot started successfully!")
        print("[BOT] Send files to get download URLs")
        print("[BOT] Press Ctrl+C to stop")

        while bot_running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("[BOT] Bot stopped by user (Ctrl+C)")
    except Exception as e:
        print(f"[ERROR] {e}")
        logger.exception("Bot error")
    finally:
        try:
            await app.stop()
            print("[BOT] Bot stopped gracefully")
        except Exception as e:
            print(f"[WARNING] Error stopping bot: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
