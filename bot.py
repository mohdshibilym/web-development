# High-Speed Telegram Download Bot with File Server for GitHub Actions
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
import math
import hashlib
from collections import defaultdict
import threading
import urllib.parse

# FastAPI for file server
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Pyrogram imports
from pyrogram import Client, filters
from pyrogram.types import Message
import aiofiles

# Get credentials from environment
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")  
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TUNNEL_URL = os.environ.get("TUNNEL_URL", "islands-km.gl.at.ply.gg:46886")

# Verify credentials
if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("ERROR: Missing credentials! Please check GitHub secrets.")
    print(f"API_ID: {'OK' if API_ID else 'MISSING'}")
    print(f"API_HASH: {'OK' if API_HASH else 'MISSING'}")
    print(f"BOT_TOKEN: {'OK' if BOT_TOKEN else 'MISSING'}")
    sys.exit(1)

# Configuration optimized for GitHub Actions
OPTIMIZATION_CONFIG = {
    "workers": 8,
    "ipv6": False,
    "proxy": None,
    "test_mode": False,
    "chunk_size": 1 * 1024 * 1024,
    "max_concurrent_downloads": 2,
    "max_connections_per_download": 5,
    "use_temp_files": True,
    "buffer_size": 8192,
    "max_retries": 3,
    "retry_delay": 2,
    "progress_update_interval": 2.0,
}

# Setup logging with UTF-8 encoding
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler with UTF-8
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# File handler with UTF-8
try:
    file_handler = logging.FileHandler('bot.log', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Could not create file handler: {e}")

# Paths for GitHub Actions runner
DOWNLOAD_PATH = os.path.join(os.getcwd(), "downloads")
TEMP_PATH = os.path.join(os.getcwd(), "temp")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(TEMP_PATH, exist_ok=True)

# Global variables
bot_running = True
active_downloads = {}
transfer_locks = defaultdict(asyncio.Lock)
download_semaphore = None
shutdown_event = asyncio.Event()

# FastAPI app for file server
app_server = FastAPI(title="Telegram Bot File Server", description="Direct download server")

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
                    
                if len(self.speed_history) > 10:
                    self.speed_history = self.speed_history[-10:]
        
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
        
        progress = (self.downloaded_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0
        remaining_bytes = self.total_bytes - self.downloaded_bytes
        eta_seconds = remaining_bytes / current_speed if current_speed > 0 else 0
        
        return {
            'elapsed': elapsed,
            'progress': progress,
            'downloaded': self.downloaded_bytes,
            'total': self.total_bytes,
            'avg_speed': avg_speed,
            'current_speed': current_speed,
            'peak_speed': self.peak_speed,
            'eta': eta_seconds
        }

class OptimizedDownloader:
    def __init__(self, client: Client):
        self.client = client
        self.speed_tracker = AdvancedSpeedTracker()

    async def download_with_retry(self, message: Message, file_path: str, max_retries: int = 3):
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
        self.speed_tracker.update_progress(current, total)
        stats = self.speed_tracker.get_advanced_stats()
        
        if stats and stats['elapsed'] > 0:
            current_time = time.time()
            if current_time - self.speed_tracker.last_progress_time >= OPTIMIZATION_CONFIG["progress_update_interval"]:
                logger.info(f"Progress: {stats['progress']:.1f}% | Speed: {format_speed(stats['current_speed'])} | ETA: {format_time(stats['eta'])}")
                self.speed_tracker.last_progress_time = current_time

def format_bytes(bytes_value):
    if bytes_value == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} TB"

def format_speed(bytes_per_second):
    return f"{format_bytes(bytes_per_second)}/s"

def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"

def get_file_info(message: Message):
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
    safe_name = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    return safe_name if safe_name and safe_name != "." else f"file_{int(time.time())}"

def create_download_link(filename: str) -> str:
    encoded_filename = urllib.parse.quote(filename)
    return f"http://{TUNNEL_URL}/download/{encoded_filename}"

# FastAPI Routes
@app_server.get("/")
async def root():
    files = []
    if os.path.exists(DOWNLOAD_PATH):
        for file in os.listdir(DOWNLOAD_PATH):
            if os.path.isfile(os.path.join(DOWNLOAD_PATH, file)):
                size = os.path.getsize(os.path.join(DOWNLOAD_PATH, file))
                files.append({
                    "name": file, 
                    "size": format_bytes(size), 
                    "download_link": f"/download/{urllib.parse.quote(file)}"
                })
    
    return {
        "message": "Telegram Bot File Server - Running on GitHub Actions",
        "tunnel_url": TUNNEL_URL,
        "files": files,
        "total_files": len(files)
    }

@app_server.get("/download/{filename}")
async def download_file(filename: str):
    filename = urllib.parse.unquote(filename)
    file_path = os.path.join(DOWNLOAD_PATH, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream'
    )

@app_server.get("/files")
async def list_files():
    files = []
    if os.path.exists(DOWNLOAD_PATH):
        for file in os.listdir(DOWNLOAD_PATH):
            file_path = os.path.join(DOWNLOAD_PATH, file)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                files.append({
                    "name": file,
                    "size": size,
                    "size_formatted": format_bytes(size),
                    "download_url": f"http://{TUNNEL_URL}/download/{urllib.parse.quote(file)}"
                })
    return {"files": files}

# Initialize Pyrogram client
app = Client(
    "github_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=OPTIMIZATION_CONFIG["workers"],
    ipv6=OPTIMIZATION_CONFIG["ipv6"],
    proxy=OPTIMIZATION_CONFIG["proxy"],
    test_mode=OPTIMIZATION_CONFIG["test_mode"]
)

@app.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_download_with_link(client, message: Message):
    global download_semaphore
    if download_semaphore is None:
        download_semaphore = asyncio.Semaphore(OPTIMIZATION_CONFIG["max_concurrent_downloads"])
        
    async with download_semaphore:
        try:
            user_name = message.from_user.first_name if message.from_user else "Unknown"
            logger.info(f"Download started by {user_name}")
            
            file_obj, file_name, file_size = get_file_info(message)
            if not file_obj:
                await message.reply_text("ERROR: Unsupported file type")
                return
            
            logger.info(f"File: {file_name}, Size: {format_bytes(file_size)}")
            
            if file_size > 2 * 1024 * 1024 * 1024:  # 2GB limit
                await message.reply_text("ERROR: File too large for GitHub Actions (>2GB)")
                return
            
            if file_size == 0:
                await message.reply_text("WARNING: Cannot determine file size")
                return
            
            safe_filename = sanitize_filename(file_name)
            file_path = os.path.join(DOWNLOAD_PATH, safe_filename)
            
            status_msg = await message.reply_text(
                f"**Download Starting**\n\n"
                f"File: {file_name}\n"
                f"Size: {format_bytes(file_size)}\n"
                f"GitHub Actions Runner"
            )
            
            download_id = f"{message.chat.id}_{message.id}"
            active_downloads[download_id] = {
                'start_time': time.time(),
                'file_name': file_name,
                'file_size': file_size
            }
            
            downloader = OptimizedDownloader(client)
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
                    
                    download_link = create_download_link(safe_filename)
                    
                    logger.info(f"Download completed: {downloaded_file}")
                    logger.info(f"Direct link: {download_link}")
                    
                    await status_msg.edit_text(
                        f"**Download Complete!**\n\n"
                        f"**File:** {file_name}\n"
                        f"**Size:** {format_bytes(actual_size)}\n"
                        f"**Time:** {format_time(download_time)}\n"
                        f"**Avg Speed:** {format_speed(stats['avg_speed'])}\n\n"
                        f"**Direct Download:**\n"
                        f"`{download_link}`\n\n"
                        f"**Access files at:** `http://{TUNNEL_URL}`"
                    )
                    
                else:
                    await status_msg.edit_text("ERROR: Download failed")
                    
            except Exception as download_error:
                logger.error(f"Download error: {download_error}")
                await status_msg.edit_text(f"ERROR: Download failed: {str(download_error)}")
            finally:
                if download_id in active_downloads:
                    del active_downloads[download_id]
                    
        except Exception as e:
            logger.error(f"Error: {e}")
            await message.reply_text(f"ERROR: {str(e)}")

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text(
        f"**GitHub Actions Telegram Bot**\n\n"
        f"**Running on GitHub Actions**\n"
        f"**Tunnel:** `{TUNNEL_URL}`\n"
        f"**Workers:** {OPTIMIZATION_CONFIG['workers']}\n\n"
        f"**Send files to get direct download links!**\n\n"
        f"**Commands:**\n"
        f"/start - Show this message\n"
        f"/status - Check status\n"
        f"/files - List files with links"
    )

@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    files = []
    total_size = 0
    try:
        if os.path.exists(DOWNLOAD_PATH):
            for file in os.listdir(DOWNLOAD_PATH):
                file_path = os.path.join(DOWNLOAD_PATH, file)
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    files.append((file, size))
                    total_size += size
    except Exception as e:
        await message.reply_text(f"ERROR: {str(e)}")
        return
    
    status_text = f"**Bot Status**\n\n"
    status_text += f"**Server:** `{TUNNEL_URL}`\n"
    status_text += f"**Files:** {len(files)} ({format_bytes(total_size)})\n"
    status_text += f"**Active:** {len(active_downloads)}\n"
    status_text += f"**Platform:** GitHub Actions\n\n"
    
    if files:
        status_text += "**Recent Files:**\n"
        for file, size in files[-3:]:
            display_name = file[:20] + "..." if len(file) > 20 else file
            status_text += f"• {display_name} ({format_bytes(size)})\n"
    
    await message.reply_text(status_text)

@app.on_message(filters.command("files"))
async def files_command(client, message: Message):
    files = []
    if os.path.exists(DOWNLOAD_PATH):
        for file in os.listdir(DOWNLOAD_PATH):
            file_path = os.path.join(DOWNLOAD_PATH, file)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                download_link = create_download_link(file)
                files.append((file, size, download_link))
    
    if not files:
        await message.reply_text("No files available")
        return
    
    files_text = f"**Available Files:**\n\n"
    for file, size, link in files[-5:]:
        display_name = file[:25] + "..." if len(file) > 25 else file
        files_text += f"**{display_name}**\n"
        files_text += f"{format_bytes(size)}\n"
        files_text += f"`{link}`\n\n"
    
    await message.reply_text(files_text)

def run_file_server():
    """Run FastAPI server"""
    try:
        uvicorn.run(app_server, host="0.0.0.0", port=8080, log_level="info")
    except Exception as e:
        logger.error(f"File server error: {e}")

async def safe_shutdown():
    """Safely shutdown all running tasks"""
    global bot_running
    bot_running = False
    shutdown_event.set()
    
    logger.info("Starting safe shutdown...")
    
    try:
        # Stop the Pyrogram client first
        await app.stop()
        logger.info("Pyrogram client stopped")
    except Exception as e:
        logger.error(f"Error stopping Pyrogram client: {e}")
    
    # Wait a moment for tasks to finish naturally
    await asyncio.sleep(1)
    
    # Cancel remaining tasks safely
    current_task = asyncio.current_task()
    tasks = [task for task in asyncio.all_tasks() if task != current_task and not task.done()]
    
    if tasks:
        logger.info(f"Cancelling {len(tasks)} remaining tasks...")
        for task in tasks:
            try:
                task.cancel()
            except Exception as e:
                logger.error(f"Error cancelling task: {e}")
        
        # Wait for tasks to be cancelled, but don't wait forever
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("Some tasks did not cancel within timeout")
        except Exception as e:
            logger.error(f"Error during task cleanup: {e}")
    
    logger.info("Safe shutdown completed")

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    
    # Create a new event loop if none exists
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Schedule the shutdown
    if loop.is_running():
        asyncio.create_task(safe_shutdown())
    else:
        loop.run_until_complete(safe_shutdown())

async def main():
    global bot_running, download_semaphore
    
    # Initialize semaphore
    download_semaphore = asyncio.Semaphore(OPTIMIZATION_CONFIG["max_concurrent_downloads"])
    
    logger.info("Starting Telegram Bot with File Server on GitHub Actions...")
    logger.info(f"Download Path: {DOWNLOAD_PATH}")
    logger.info(f"Tunnel URL: {TUNNEL_URL}")
    logger.info(f"File Server: Port 8080")
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start file server in background thread
    server_thread = threading.Thread(target=run_file_server, daemon=True)
    server_thread.start()
    logger.info("File server started on port 8080")
    
    try:
        await app.start()
        logger.info("Telegram bot started successfully!")
        logger.info(f"Access files at: http://{TUNNEL_URL}")
        
        # Keep running until shutdown
        while bot_running and not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                break
                
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        await safe_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        print("Bot shutdown complete")
