# High-Speed Telegram Download Bot with File Server - Fixed for Windows
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

# Fix encoding for Windows
if os.name == 'nt':  # Windows
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

# Install required packages
"""
pip install pyrogram TgCrypto aiofiles aiohttp requests cryptg
"""

from pyrogram import Client, filters
from pyrogram.types import Message
import aiofiles

# Configuration
API_ID = os.getenv("API_ID", "12345678")
API_HASH = os.getenv("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")

# GitHub Actions paths
DOWNLOAD_PATH = os.path.join(os.getcwd(), "downloads")
TEMP_PATH = os.path.join(os.getcwd(), "temp")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(TEMP_PATH, exist_ok=True)

# Server configuration
SERVER_PORT = 8080
PUBLIC_URL = "http://islands-km.gl.at.ply.gg:46886"

# Maximum number of parallel connections
MAX_CONNECTIONS = 20

# Advanced Configuration for Speed Optimization
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

# Setup logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
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
                # Reduce server logs
                pass
                
            def end_headers(self):
                # Add CORS headers
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
        self.chunk_times = []

    def start_download(self, total_size):
        self.start_time = time.time()
        self.last_update = self.start_time
        self.total_bytes = total_size
        self.downloaded_bytes = 0
        self.speed_history = []
        self.last_progress_time = 0
        self.peak_speed = 0
        self.chunk_times = []

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

# Initialize optimized Pyrogram client
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
                
                # Update Telegram status every 5 seconds
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

# Rest of your bot code with all emojis replaced with text equivalents...
# [Continue with the rest of the functions, replacing emojis with text]

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

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global bot_running
    print(f"[SIGNAL] Received signal {signum}, stopping bot...")
    bot_running = False

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
