import os
import time
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

# --- CONFIGURATION ---
# It's better to put these in Railway's Environment Variables
API_ID = int(os.environ.get("API_ID", "YOUR_API_ID_HERE")) 
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH_HERE")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

app = Client("handbrake_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Helper function to track download/upload progress
async def progress_for_pyrogram(current, total, ud_type, message, start):
    now = time.time()
    diff = now - start
    if round(diff % 5.00) == 0 or current == total: # Update every 5 seconds to avoid FloodWait
        percentage = current * 100 / total
        try:
            await message.edit_text(f"{ud_type} Progress: {percentage:.2f}%")
        except:
            pass # Ignore if the message is exactly the same

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Send me an H.265 video/document and I'll convert it to H.264 using HandBrake at full speed!")

@app.on_message(filters.video | filters.document)
async def convert_video(client, message: Message):
    msg = await message.reply_text("📥 Downloading video...")
    start_time = time.time()
    
    # 1. Download the file
    input_file = await message.download(
        progress=progress_for_pyrogram,
        progress_args=("📥 Downloading...", msg, start_time)
    )
    
    if not input_file:
        return await msg.edit_text("❌ Download failed.")

    output_file = f"converted_{message.id}.mp4"
    await msg.edit_text("⚙️ Starting HandBrake conversion...")

    # 2. Run HandBrake CLI process
    # preset "ultrafast" ensures full speed. You can change to "fast" if you want better compression.
    cmd = [
        "HandBrakeCLI",
        "-i", input_file,
        "-o", output_file,
        "-e", "x264",       # Encode to H.264
        "--preset", "ultrafast", # Maximum speed
        "--all-audio"       # Keep audio tracks
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    # 3. Read HandBrake progress in real-time
    last_update = time.time()
    while True:
        line = await process.stdout.readline()
        if not line:
            break
            
        line_text = line.decode('utf-8').strip()
        
        # Handbrake output looks like: "Encoding: task 1 of 1, 45.22 %"
        match = re.search(r'(\d+\.\d+)\s*%', line_text)
        if match:
            percentage = match.group(1)
            now = time.time()
            # Update Telegram message every 5 seconds
            if now - last_update > 5:
                try:
                    await msg.edit_text(f"⚙️ Converting: {percentage}% done")
                    last_update = now
                except:
                    pass

    await process.wait()

    if os.path.exists(output_file):
        await msg.edit_text("📤 Uploading converted video...")
        
        # 4. Upload the converted file
        up_start = time.time()
        await message.reply_video(
            video=output_file,
            caption="Here is your H.264 converted video! 🎬",
            progress=progress_for_pyrogram,
            progress_args=("📤 Uploading...", msg, up_start)
        )
        await msg.delete() # Cleanup status message
        
        # Cleanup local files
        os.remove(input_file)
        os.remove(output_file)
    else:
        await msg.edit_text("❌ Conversion failed. Please check if the file was a valid video.")
        os.remove(input_file)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
