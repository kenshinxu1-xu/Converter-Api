// ═══════════════════════════════════════════════════════════════
//  KENSHIN VIDEO CONVERTER — server.js (single file, no subfolders)
//  Deploy: Railway → Dockerfile auto-detect
//  Made for: animeverse.42web.io
// ═══════════════════════════════════════════════════════════════

const express    = require('express');
const cors       = require('cors');
const path       = require('path');
const fs         = require('fs');
const crypto     = require('crypto');
const https      = require('https');
const http       = require('http');
const { URL }    = require('url');
const { spawn, execFile } = require('child_process');

const app  = express();
const PORT = process.env.PORT || 3000;
const TMP  = '/tmp/kenshin-hls';

// ── Temp dir ──
if (!fs.existsSync(TMP)) fs.mkdirSync(TMP, { recursive: true });

// ── CORS ──
app.use(cors({ origin: '*', methods: ['GET','POST','OPTIONS'], allowedHeaders: ['Content-Type','Range'] }));
app.use(express.json({ limit: '1mb' }));

// ── Base URL helper ──
function baseUrl(req) {
  if (process.env.RAILWAY_PUBLIC_DOMAIN) return `https://${process.env.RAILWAY_PUBLIC_DOMAIN}`;
  return `${req.protocol}://${req.get('host')}`;
}

// ══════════════════════════════════════════════════════════════
// QUALITY PRESETS
// ══════════════════════════════════════════════════════════════
const PRESETS = {
  '360p':  { scale: '640:360',   crf: 26, preset: 'fast' },
  '480p':  { scale: '854:480',   crf: 23, preset: 'fast' },
  '720p':  { scale: '1280:720',  crf: 20, preset: 'fast' },
  '1080p': { scale: '1920:1080', crf: 18, preset: 'fast' },
  '4K':    { scale: '3840:2160', crf: 16, preset: 'medium' },
  '8K':    { scale: '7680:4320', crf: 14, preset: 'medium' },
  'source': { scale: null,       crf: 18, preset: 'fast'   },
};

// ══════════════════════════════════════════════════════════════
// GET / — health check
// ══════════════════════════════════════════════════════════════
app.get('/', (req, res) => {
  res.json({
    service: '🎌 Kenshin Video Converter',
    version: '2.0.0',
    status:  'running ✅',
    endpoints: {
      'POST /info':        'Check codec of any video URL',
      'POST /hls':         'Convert any video → HLS stream (auto H.264+AAC)',
      'GET  /hls/status/:id': 'Check conversion progress',
      'GET  /hls/play/:id/index.m3u8': 'Serve converted HLS',
      'GET  /hls/fetch':   'CORS proxy for existing HLS streams',
      'GET  /stream':      'CORS proxy for direct video files',
      'GET  /convert/play':'On-the-fly convert + stream as MP4',
    }
  });
});

// ══════════════════════════════════════════════════════════════
// POST /info — check video codec, resolution, browser compat
// ══════════════════════════════════════════════════════════════
app.post('/info', (req, res) => {
  const { url } = req.body;
  if (!url) return res.status(400).json({ ok: false, error: 'URL required' });

  execFile('ffprobe', [
    '-v', 'quiet', '-print_format', 'json',
    '-show_streams', '-show_format', url,
  ], { timeout: 30000 }, (err, stdout) => {
    if (err) return res.status(500).json({ ok: false, error: 'ffprobe failed: ' + err.message });

    let info;
    try { info = JSON.parse(stdout); }
    catch(e) { return res.status(500).json({ ok: false, error: 'Parse error' }); }

    const streams    = info.streams || [];
    const video      = streams.find(s => s.codec_type === 'video');
    const audio      = streams.find(s => s.codec_type === 'audio');
    const videoCodec = video?.codec_name || 'unknown';
    const audioCodec = audio?.codec_name || 'unknown';
    const height     = video?.height || 0;
    const duration   = parseFloat(info.format?.duration || 0);
    const videoOk    = ['h264','avc1','vp8','vp9','av1'].includes(videoCodec.toLowerCase());
    const audioOk    = ['aac','mp3','opus','vorbis','flac'].includes(audioCodec.toLowerCase());

    const resLabel = height>=4320?'8K':height>=2160?'4K':height>=1440?'2K':
                     height>=1080?'1080p':height>=720?'720p':height>=480?'480p':
                     height>=360?'360p':`${height}p`;

    res.json({
      ok: true,
      video:  { codec: videoCodec, width: video?.width||0, height, label: resLabel, browserOk: videoOk },
      audio:  { codec: audioCodec, channels: audio?.channels||0, browserOk: audioOk },
      duration: Math.round(duration),
      durationLabel: duration ? `${Math.floor(duration/60)}m ${Math.floor(duration%60)}s` : 'unknown',
      needsConvert:  !videoOk || !audioOk,
      convertReason: !videoOk ? `Video: "${videoCodec}" → needs H.264`
                   : !audioOk ? `Audio: "${audioCodec}" → needs AAC` : null,
    });
  });
});

// ══════════════════════════════════════════════════════════════
// HLS JOBS MAP
// ══════════════════════════════════════════════════════════════
const jobs = new Map();

// ══════════════════════════════════════════════════════════════
// POST /hls — convert any video to HLS (m3u8+ts)
// ══════════════════════════════════════════════════════════════
app.post('/hls', (req, res) => {
  const { url, quality = 'source' } = req.body;
  if (!url || !url.startsWith('http')) return res.status(400).json({ ok:false, error:'Valid URL required' });

  const id      = crypto.randomBytes(8).toString('hex');
  const outDir  = path.join(TMP, id);
  const m3u8    = path.join(outDir, 'index.m3u8');
  const preset  = PRESETS[quality] || PRESETS['source'];
  const base    = baseUrl(req);
  const playUrl = `${base}/hls/play/${id}/index.m3u8`;

  fs.mkdirSync(outDir, { recursive: true });
  jobs.set(id, { status:'processing', outDir, startedAt: Date.now() });

  const ffArgs = [
    '-loglevel', 'warning',
    '-i', url,
    // Video H.264
    '-c:v','libx264','-preset','fast',
    '-crf', String(preset.crf),
    '-profile:v','high','-level:v','4.1',
    '-pix_fmt','yuv420p',
    '-g','48','-sc_threshold','0',
    ...(preset.scale ? ['-vf',`scale=${preset.scale}:force_original_aspect_ratio=decrease,pad=${preset.scale}:(ow-iw)/2:(oh-ih)/2`] : []),
    // Audio AAC
    '-c:a','aac','-b:a','192k','-ac','2','-ar','48000',
    // HLS
    '-f','hls','-hls_time','4','-hls_list_size','0',
    '-hls_segment_type','mpegts',
    '-hls_flags','independent_segments',
    '-hls_segment_filename', path.join(outDir,'seg%04d.ts'),
    m3u8,
  ];

  console.log(`[HLS] Job ${id}: ${url} → ${quality}`);
  const ff = spawn('ffmpeg', ffArgs);

  ff.stderr.on('data', d => process.stdout.write('[HLS] '+d));
  ff.on('error', err => {
    console.error('[HLS] Error:', err.message);
    if (jobs.has(id)) jobs.set(id, { ...jobs.get(id), status:'error', error: err.message });
  });
  ff.on('close', code => {
    console.log(`[HLS] Job ${id} done code=${code}`);
    if (jobs.has(id)) jobs.set(id, { ...jobs.get(id), status: code===0?'done':'error' });
    // Auto cleanup after 2h
    setTimeout(() => {
      try { fs.rmSync(outDir, { recursive:true, force:true }); } catch(e){}
      jobs.delete(id);
    }, 2*60*60*1000);
  });

  res.json({
    ok: true, id,
    playUrl,
    statusUrl: `${base}/hls/status/${id}`,
    quality,
    message: 'Started. playUrl ready in ~8s. Poll statusUrl.',
  });
});

// ── GET /hls/status/:id ──
app.get('/hls/status/:id', (req, res) => {
  const job = jobs.get(req.params.id);
  if (!job) return res.status(404).json({ ok:false, error:'Not found or expired' });
  let segs = 0;
  try { segs = fs.readdirSync(job.outDir).filter(f=>f.endsWith('.ts')).length; } catch(e){}
  res.json({
    ok:true, status:job.status, segments:segs,
    ready: segs >= 2,
    elapsed: Math.round((Date.now()-job.startedAt)/1000)+'s',
    error: job.error||null,
  });
});

// ── GET /hls/play/:id/* — serve m3u8 + ts segments ──
app.get('/hls/play/:id/*', (req, res) => {
  const job = jobs.get(req.params.id);
  if (!job) return res.status(404).send('Job expired');
  const file     = req.params[0] || 'index.m3u8';
  const filePath = path.join(job.outDir, path.basename(file));
  if (!fs.existsSync(filePath)) return res.status(404).send('Not ready yet');
  const mime = filePath.endsWith('.m3u8') ? 'application/vnd.apple.mpegurl' : 'video/mp2t';
  res.setHeader('Content-Type', mime);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-cache');
  fs.createReadStream(filePath).pipe(res);
});

// ── GET /hls/fetch — CORS proxy for existing HLS m3u8/ts ──
app.get('/hls/fetch', async (req, res) => {
  const { url } = req.query;
  if (!url) return res.status(400).send('url required');
  try {
    const fetch = (await import('node-fetch')).default;
    const r = await fetch(decodeURIComponent(url), {
      headers:{ 'User-Agent':'Mozilla/5.0 (compatible; KenshinProxy/1.0)' }
    });
    if (!r.ok) return res.status(r.status).send('Upstream error');
    res.setHeader('Content-Type', r.headers.get('content-type')||'application/octet-stream');
    res.setHeader('Access-Control-Allow-Origin','*');
    res.setHeader('Cache-Control','no-cache');
    r.body.pipe(res);
  } catch(err) { res.status(500).json({ ok:false, error:err.message }); }
});

// ══════════════════════════════════════════════════════════════
// GET /stream?url=... — CORS proxy with Range support
// ══════════════════════════════════════════════════════════════
app.get('/stream', (req, res) => {
  const { url } = req.query;
  if (!url) return res.status(400).json({ ok:false, error:'url required' });

  let target;
  try { target = new URL(decodeURIComponent(url)); }
  catch(e) { return res.status(400).json({ ok:false, error:'Invalid URL' }); }

  const proto   = target.protocol === 'https:' ? https : http;
  const headers = {
    'User-Agent': 'Mozilla/5.0 (compatible; KenshinProxy/1.0)',
    'Accept': '*/*', 'Accept-Encoding': 'identity',
  };
  if (req.headers.range) headers['Range'] = req.headers.range;

  const proxyReq = proto.request(
    { hostname:target.hostname, path:target.pathname+target.search, headers },
    proxyRes => {
      res.status(proxyRes.statusCode||200);
      res.setHeader('Access-Control-Allow-Origin','*');
      res.setHeader('Access-Control-Expose-Headers','Content-Range,Content-Length,Accept-Ranges');
      ['content-type','content-length','content-range','accept-ranges','last-modified'].forEach(h => {
        const v = proxyRes.headers[h]; if(v) res.setHeader(h,v);
      });
      proxyRes.pipe(res);
    }
  );
  proxyReq.on('error', err => { if(!res.headersSent) res.status(502).json({ok:false,error:err.message}); });
  proxyReq.end();
  req.on('close', () => proxyReq.destroy());
});

// ══════════════════════════════════════════════════════════════
// GET /convert/play?url=&quality= — on-the-fly convert stream as fMP4
// (video.src = this URL → direct browser play)
// ══════════════════════════════════════════════════════════════
app.get('/convert/play', (req, res) => {
  const { url, quality='source' } = req.query;
  if (!url) return res.status(400).send('url required');
  const preset = PRESETS[quality] || PRESETS['source'];

  const ffArgs = [
    '-loglevel','warning',
    '-i', decodeURIComponent(url),
    '-c:v','libx264','-preset',preset.preset,
    '-crf',String(preset.crf),
    '-profile:v','high','-level:v','4.2',
    '-pix_fmt','yuv420p',
    '-movflags','+faststart+frag_keyframe+empty_moov',
    ...(preset.scale ? ['-vf',`scale=${preset.scale}:force_original_aspect_ratio=decrease`] : []),
    '-c:a','aac','-b:a','192k','-ac','2','-ar','48000',
    '-f','mp4','pipe:1',
  ];

  res.setHeader('Content-Type','video/mp4');
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Cache-Control','no-cache');

  const ff = spawn('ffmpeg', ffArgs);
  ff.stdout.pipe(res);
  ff.stderr.on('data', d => process.stdout.write('[CONV] '+d));
  ff.on('error', err => { if(!res.headersSent) res.status(500).send(err.message); });
  ff.on('close', () => { if(!res.writableEnded) res.end(); });
  req.on('close', () => { if(ff&&!ff.killed) ff.kill('SIGKILL'); });
});

// ── Error handler ──
app.use((err,req,res,_n) => res.status(500).json({ ok:false, error:err.message }));

app.listen(PORT, () => console.log(`✅ Kenshin Converter running on port ${PORT}`));
