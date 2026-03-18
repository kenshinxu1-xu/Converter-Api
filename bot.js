// ═══════════════════════════════════════════════════════════════
//  KENSHIN VIDEO CONVERTER BOT — bot.js (single file)
//  Supports: Video file upload + URL + HLS link
//  Output: H.264 video + AAC audio (browser-safe)
//  Deploy: Railway → set BOT_TOKEN env variable
// ═══════════════════════════════════════════════════════════════

const TelegramBot = require('node-telegram-bot-api');
const { spawn, execFile } = require('child_process');
const https  = require('https');
const http   = require('http');
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

// ── Config ──
const BOT_TOKEN = process.env.BOT_TOKEN;
if (!BOT_TOKEN) { console.error('❌ BOT_TOKEN env variable not set!'); process.exit(1); }

const TMP = '/tmp/kenshin-bot';
if (!fs.existsSync(TMP)) fs.mkdirSync(TMP, { recursive: true });

const bot = new TelegramBot(BOT_TOKEN, { polling: true });

console.log('✅ Kenshin Converter Bot started!');

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function uid() { return crypto.randomBytes(6).toString('hex'); }

function fmt(s) {
  if (!s || isNaN(s)) return '0:00';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sc = Math.floor(s % 60);
  return h > 0
    ? `${h}:${m.toString().padStart(2,'0')}:${sc.toString().padStart(2,'0')}`
    : `${m}:${sc.toString().padStart(2,'0')}`;
}

function cleanTmp(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch(e) {}
}

// Download file from URL to local path
function download(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http;
    const file  = fs.createWriteStream(dest);
    proto.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, res => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        file.close();
        return download(res.headers.location, dest).then(resolve).catch(reject);
      }
      res.pipe(file);
      file.on('finish', () => { file.close(); resolve(dest); });
    }).on('error', err => { fs.unlink(dest, ()=>{}); reject(err); });
  });
}

// Get video codec info via ffprobe
function getInfo(inputPath) {
  return new Promise((resolve) => {
    execFile('ffprobe', [
      '-v','quiet','-print_format','json',
      '-show_streams','-show_format', inputPath
    ], { timeout: 60000 }, (err, stdout) => {
      if (err) return resolve(null);
      try {
        const info    = JSON.parse(stdout);
        const streams = info.streams || [];
        const video   = streams.find(s => s.codec_type === 'video');
        const audio   = streams.find(s => s.codec_type === 'audio');
        const h       = video?.height || 0;
        resolve({
          videoCodec:   video?.codec_name || 'unknown',
          audioCodec:   audio?.codec_name || 'unknown',
          width:        video?.width  || 0,
          height:       h,
          label:        h>=4320?'8K':h>=2160?'4K':h>=1440?'2K':h>=1080?'1080p':h>=720?'720p':h>=480?'480p':h>=360?'360p':`${h}p`,
          duration:     parseFloat(info.format?.duration || 0),
          size:         parseInt(info.format?.size || 0),
          needsConvert: !['h264','avc1','vp8','vp9','av1'].includes((video?.codec_name||'').toLowerCase())
                     || !['aac','mp3','opus','vorbis'].includes((audio?.codec_name||'').toLowerCase()),
        });
      } catch(e) { resolve(null); }
    });
  });
}

// Convert to H.264+AAC — returns output file path
function convert(inputPath, outputPath, onProgress) {
  return new Promise((resolve, reject) => {
    const ffArgs = [
      '-y',
      '-i', inputPath,
      // Video → H.264 original quality
      '-c:v','libx264',
      '-preset','fast',
      '-crf','18',
      '-profile:v','high',
      '-level:v','4.2',
      '-pix_fmt','yuv420p',
      '-movflags','+faststart',
      // Audio → AAC stereo (fixes AC3/DTS/5.1)
      '-c:a','aac',
      '-b:a','192k',
      '-ac','2',
      '-ar','48000',
      outputPath,
    ];

    console.log(`[CONVERT] ${path.basename(inputPath)} → ${path.basename(outputPath)}`);
    const ff      = spawn('ffmpeg', ffArgs);
    let   durSec  = 0;
    let   lastPct = -1;

    ff.stderr.on('data', chunk => {
      const line = chunk.toString();

      // Parse duration
      if (!durSec) {
        const dm = line.match(/Duration:\s*(\d+):(\d+):(\d+)/);
        if (dm) durSec = parseInt(dm[1])*3600 + parseInt(dm[2])*60 + parseInt(dm[3]);
      }

      // Parse progress
      const tm = line.match(/time=(\d+):(\d+):(\d+)/);
      if (tm && durSec > 0) {
        const cur = parseInt(tm[1])*3600 + parseInt(tm[2])*60 + parseInt(tm[3]);
        const pct = Math.min(99, Math.round(cur / durSec * 100));
        if (pct !== lastPct && onProgress) { lastPct = pct; onProgress(pct, cur, durSec); }
      }
    });

    ff.on('error', err => reject(new Error('FFmpeg not found: ' + err.message)));
    ff.on('close', code => {
      if (code === 0) resolve(outputPath);
      else reject(new Error(`FFmpeg exited with code ${code}`));
    });
  });
}

// ═══════════════════════════════════════════════════════════════
// BOT COMMANDS
// ═══════════════════════════════════════════════════════════════

bot.onText(/\/start/, (msg) => {
  bot.sendMessage(msg.chat.id,
`🎌 *Kenshin Video Converter Bot*

Mujhe bhejo:
• 🎬 *Video file* — direct upload karo
• 🔗 *Video URL* — catbox, direct MP4/MKV link
• 📺 *HLS link* — .m3u8 streaming URL

Main automatically convert karunga:
H.265 → H.264 ✅
AC3/DTS → AAC ✅
MKV → MP4 ✅

Converted video seedha website pe chalegi! 🚀

Commands:
/start — Yeh message
/help  — Help`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📖 *Help*

*Video bhejne ke 3 tarike:*

1️⃣ *Direct upload:*
   Telegram mein video file attach karke bhejo

2️⃣ *URL bhejo:*
   \`https://files.catbox.moe/abc123.mkv\`

3️⃣ *HLS link bhejo:*
   \`https://example.com/stream/index.m3u8\`

*Supported input:*
MKV, MP4, AVI, WebM, HLS (.m3u8)

*Converted output:*
H.264 + AAC MP4 — Chrome/Firefox/Safari sab pe chalega ✅`,
    { parse_mode: 'Markdown' }
  );
});

// ═══════════════════════════════════════════════════════════════
// VIDEO FILE HANDLER
// ═══════════════════════════════════════════════════════════════

bot.on('video', async (msg) => {
  const chatId = msg.chat.id;
  const video  = msg.video;
  const id     = uid();
  const dir    = path.join(TMP, id);
  fs.mkdirSync(dir, { recursive: true });

  const statusMsg = await bot.sendMessage(chatId, '⏳ Video mil gayi — info check kar raha hoon...');
  const edit = (text) => bot.editMessageText(text, { chat_id: chatId, message_id: statusMsg.message_id, parse_mode: 'Markdown' });

  try {
    // Get file URL from Telegram
    await edit('📥 *Download ho rahi hai...*');
    const fileInfo = await bot.getFile(video.file_id);
    const fileUrl  = `https://api.telegram.org/file/bot${BOT_TOKEN}/${fileInfo.file_path}`;
    const inputExt = path.extname(fileInfo.file_path) || '.mp4';
    const inputPath  = path.join(dir, `input${inputExt}`);
    const outputPath = path.join(dir, 'output.mp4');

    await download(fileUrl, inputPath);
    await edit('🔍 *Codec check kar raha hoon...*');

    const info = await getInfo(inputPath);
    if (!info) { await edit('❌ Video info nahi mili. Dobara try karo.'); return cleanTmp(dir); }

    const infoText = `📊 *Video Info:*\n`
      + `• Resolution: \`${info.label}\` (${info.width}×${info.height})\n`
      + `• Video Codec: \`${info.videoCodec.toUpperCase()}\`\n`
      + `• Audio Codec: \`${info.audioCodec.toUpperCase()}\`\n`
      + `• Duration: \`${fmt(info.duration)}\`\n`;

    if (!info.needsConvert) {
      await edit(infoText + '\n✅ *Already H.264+AAC hai!*\nConversion ki zarurat nahi.');
      await bot.sendVideo(chatId, inputPath, { caption: '✅ Original file (already browser-safe!)' });
      return cleanTmp(dir);
    }

    await edit(infoText + '\n⚙️ *Convert ho rahi hai...*\n`[░░░░░░░░░░] 0%`');

    let lastUpdate = 0;
    await convert(inputPath, outputPath, async (pct, cur, dur) => {
      const now = Date.now();
      if (now - lastUpdate < 4000) return; // update every 4s
      lastUpdate = now;
      const filled = Math.round(pct / 10);
      const bar    = '█'.repeat(filled) + '░'.repeat(10 - filled);
      await edit(infoText + `\n⚙️ *Convert ho rahi hai...*\n\`[${bar}] ${pct}%\`\n⏱ \`${fmt(cur)} / ${fmt(dur)}\``).catch(()=>{});
    });

    // Check output file
    const outSize = fs.statSync(outputPath).size;
    await edit(infoText + `\n✅ *Convert ho gayi!*\n📦 Size: \`${(outSize/1024/1024).toFixed(1)} MB\`\n📤 *Upload ho rahi hai...*`);

    await bot.sendVideo(chatId, outputPath, {
      caption: `✅ *Converted: ${info.videoCodec.toUpperCase()} → H.264 + AAC*\n🎬 ${info.label} | ${fmt(info.duration)}\n🌐 Ab website pe directly chalegi!`,
      parse_mode: 'Markdown',
      supports_streaming: true,
    });

    await edit(infoText + `\n✅ *Done! Video send ho gayi.* 🎌`);

  } catch(err) {
    console.error('[VIDEO]', err);
    await edit(`❌ *Error:* \`${err.message}\``).catch(()=>{});
  } finally {
    cleanTmp(dir);
  }
});

// ═══════════════════════════════════════════════════════════════
// DOCUMENT HANDLER (MKV files come as documents in Telegram)
// ═══════════════════════════════════════════════════════════════

bot.on('document', async (msg) => {
  const chatId = msg.chat.id;
  const doc    = msg.document;
  const name   = (doc.file_name || '').toLowerCase();

  // Only process video files
  if (!/\.(mp4|mkv|avi|webm|mov|flv|m4v)$/i.test(name)) {
    bot.sendMessage(chatId, '⚠️ Sirf video files support hoti hain (MP4, MKV, AVI, WebM)');
    return;
  }

  const id  = uid();
  const dir = path.join(TMP, id);
  fs.mkdirSync(dir, { recursive: true });

  const statusMsg = await bot.sendMessage(chatId, '⏳ File mil gayi — download ho rahi hai...');
  const edit = (text) => bot.editMessageText(text, { chat_id: chatId, message_id: statusMsg.message_id, parse_mode: 'Markdown' });

  try {
    const fileInfo   = await bot.getFile(doc.file_id);
    const fileUrl    = `https://api.telegram.org/file/bot${BOT_TOKEN}/${fileInfo.file_path}`;
    const ext        = path.extname(doc.file_name || '.mkv');
    const inputPath  = path.join(dir, `input${ext}`);
    const outputPath = path.join(dir, 'output.mp4');

    await edit(`📥 *Download ho rahi hai...*\n📄 \`${doc.file_name}\``);
    await download(fileUrl, inputPath);

    await edit('🔍 *Codec check kar raha hoon...*');
    const info = await getInfo(inputPath);
    if (!info) { await edit('❌ File info nahi mili.'); return cleanTmp(dir); }

    const infoText = `📊 *File Info:*\n`
      + `• File: \`${doc.file_name}\`\n`
      + `• Resolution: \`${info.label}\`\n`
      + `• Video: \`${info.videoCodec.toUpperCase()}\`\n`
      + `• Audio: \`${info.audioCodec.toUpperCase()}\`\n`
      + `• Duration: \`${fmt(info.duration)}\`\n`;

    if (!info.needsConvert) {
      await edit(infoText + '\n✅ *Already browser-safe hai!*');
      await bot.sendVideo(chatId, inputPath, { caption: '✅ Already H.264+AAC!', supports_streaming: true });
      return cleanTmp(dir);
    }

    await edit(infoText + '\n⚙️ *Converting...*\n`[░░░░░░░░░░] 0%`');

    let lastUpdate = 0;
    await convert(inputPath, outputPath, async (pct, cur, dur) => {
      if (Date.now() - lastUpdate < 4000) return;
      lastUpdate = Date.now();
      const bar = '█'.repeat(Math.round(pct/10)) + '░'.repeat(10 - Math.round(pct/10));
      await edit(infoText + `\n⚙️ *Converting...*\n\`[${bar}] ${pct}%\`\n⏱ \`${fmt(cur)} / ${fmt(dur)}\``).catch(()=>{});
    });

    const outSize = fs.statSync(outputPath).size;
    await edit(infoText + `\n✅ *Done!* Size: \`${(outSize/1024/1024).toFixed(1)} MB\`\n📤 Uploading...`);

    await bot.sendVideo(chatId, outputPath, {
      caption: `✅ *${doc.file_name} converted!*\n${info.videoCodec.toUpperCase()} → H.264 + AAC\n🌐 Website pe chalegi!`,
      parse_mode: 'Markdown',
      supports_streaming: true,
    });

  } catch(err) {
    console.error('[DOC]', err);
    await edit(`❌ *Error:* \`${err.message}\``).catch(()=>{});
  } finally {
    cleanTmp(dir);
  }
});

// ═══════════════════════════════════════════════════════════════
// URL / HLS TEXT HANDLER
// ═══════════════════════════════════════════════════════════════

bot.on('message', async (msg) => {
  if (!msg.text) return;
  if (msg.text.startsWith('/')) return; // ignore commands

  const text = msg.text.trim();
  const chatId = msg.chat.id;

  // Detect URL
  const urlMatch = text.match(/https?:\/\/[^\s]+/);
  if (!urlMatch) {
    bot.sendMessage(chatId,
      '❓ Mujhe bhejo:\n• Video file (attach karke)\n• Video URL (catbox, direct link)\n• HLS link (.m3u8)\n\n/help se details dekho'
    );
    return;
  }

  const url = urlMatch[0];
  const lo  = url.toLowerCase();
  const id  = uid();
  const dir = path.join(TMP, id);
  fs.mkdirSync(dir, { recursive: true });

  const statusMsg = await bot.sendMessage(chatId, `🔗 URL mili:\n\`${url}\`\n\n⏳ Process ho rahi hai...`, { parse_mode: 'Markdown' });
  const edit = (text) => bot.editMessageText(text, { chat_id: chatId, message_id: statusMsg.message_id, parse_mode: 'Markdown' });

  const isHLS = lo.includes('.m3u8');

  try {
    await edit(`🔗 URL: \`${url.slice(0,60)}...\`\n\n🔍 *Codec check kar raha hoon...*`);

    // Check codec info first (works for direct URLs)
    const info = await getInfo(url);

    const infoText = info
      ? `📊 *Video Info:*\n`
        + `• Resolution: \`${info.label}\`\n`
        + `• Video: \`${info.videoCodec.toUpperCase()}\`\n`
        + `• Audio: \`${info.audioCodec.toUpperCase()}\`\n`
        + `• Duration: \`${fmt(info.duration)}\`\n`
      : `🔗 *URL:* \`${url.slice(0,50)}...\`\n`;

    if (info && !info.needsConvert) {
      await edit(infoText + '\n✅ *Already H.264+AAC hai!*\nKoi conversion nahi chahiye.\n\nDirect website pe use kar sakte ho! 🌐');
      cleanTmp(dir);
      return;
    }

    await edit(infoText + `\n⚙️ *Convert ho rahi hai ${isHLS ? '(HLS stream)' : ''}...*\n\`[░░░░░░░░░░] 0%\``);

    const outputPath = path.join(dir, 'output.mp4');

    let lastUpdate = 0;
    await convert(url, outputPath, async (pct, cur, dur) => {
      if (Date.now() - lastUpdate < 5000) return;
      lastUpdate = Date.now();
      const bar = '█'.repeat(Math.round(pct/10)) + '░'.repeat(10 - Math.round(pct/10));
      await edit(infoText + `\n⚙️ *Converting ${isHLS ? '(HLS)' : ''}...*\n\`[${bar}] ${pct}%\`\n⏱ \`${fmt(cur)} / ${fmt(dur)}\``).catch(()=>{});
    });

    const outSize = fs.statSync(outputPath).size;
    const outMB   = (outSize / 1024 / 1024).toFixed(1);

    // Telegram bot limit = 50MB for sendVideo
    if (outSize > 50 * 1024 * 1024) {
      await edit(infoText + `\n⚠️ *File bahut badi hai (${outMB} MB)*\nTelegram limit 50MB hai.\n\nFile Railway server pe saved hai — direct URL use karo apni site mein.`);
      cleanTmp(dir);
      return;
    }

    await edit(infoText + `\n✅ *Convert ho gayi!* (${outMB} MB)\n📤 *Upload ho rahi hai...*`);

    await bot.sendVideo(chatId, outputPath, {
      caption: `✅ *URL se convert ho gayi!*\n${info ? info.videoCodec.toUpperCase() + ' → ' : ''}H.264 + AAC\n🌐 Website pe directly chalegi!`,
      parse_mode: 'Markdown',
      supports_streaming: true,
    });

    await edit(infoText + `\n✅ *Done! Video send ho gayi.* 🎌`);

  } catch(err) {
    console.error('[URL]', err.message);
    await edit(`❌ *Error:* \`${err.message}\`\n\nCheck karo:\n• URL sahi hai?\n• File accessible hai?`).catch(()=>{});
  } finally {
    cleanTmp(dir);
  }
});

// ── Polling error handler ──
bot.on('polling_error', err => console.error('[POLL]', err.message));

process.on('uncaughtException',  err => console.error('[CRASH]', err));
process.on('unhandledRejection', err => console.error('[REJECT]', err));
