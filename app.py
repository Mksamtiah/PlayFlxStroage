import os, asyncio, secrets, traceback, uvicorn, logging, uuid, shutil, math
from contextlib import asynccontextmanager
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pyrogram.file_id import FileId
from pyrogram import raw
from pyrogram.errors import FloodWait
from config import Config
from database import db

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 PlayFlx Server Starting...")
    await db.connect()
    try:
        await bot.start()
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        print(f"✅ Bot @{Config.BOT_USERNAME} started!")
    except Exception as e:
        print(f"❌ Bot error: {e}")
    try:
        chat = await bot.get_chat(Config.STORAGE_CHANNEL)
        print(f"✅ Storage: {chat.title}")
    except Exception as e:
        print(f"❌ Storage error: {e}")
    print("✅ Server Ready!")
    yield
    if bot.is_initialized: await bot.stop()
    await db.disconnect()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

bot = Client("PlayFlxBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN, in_memory=True)

def get_readable_file_size(size):
    if not size: return '0B'
    power, n = 1024, 0
    labels = {0:'B',1:'KB',2:'MB',3:'GB',4:'TB'}
    while size >= power and n < 4: size /= power; n += 1
    return f"{size:.2f} {labels[n]}"

@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        uid = message.command[1].split("_",1)[1]
        link = f"{Config.BASE_URL}/show/{uid}"
        await message.reply(f"✅ **Link Ready!**\n🔗 `{link}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 Open", url=link)]]), disable_web_page_preview=True)
        return
    await message.reply(f"👋 **Hello {message.from_user.first_name}!**\n\n📤 Send file = Get permanent link!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Web Upload", url=f"{Config.BASE_URL}/upload")],[InlineKeyboardButton("📁 All Files", url=f"{Config.BASE_URL}/files")]]))

@bot.on_message(filters.command("ping"))
async def ping(client, message): await message.reply("🏓 Pong!")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def user_file(client, message):
    media = message.document or message.video or message.audio
    fname, fsize = media.file_name or "Unknown", get_readable_file_size(media.file_size) if media.file_size else "N/A"
    prog = await message.reply(f"📤 Uploading `{fname}`...")
    try:
        sent = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        uid = secrets.token_urlsafe(8)
        await db.save_link(uid, sent.id)
        link = f"{Config.BASE_URL}/show/{uid}"
        await prog.edit(f"✅ **Uploaded!**\n📄 `{fname}`\n📦 {fsize}\n🔗 `{link}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 Open", url=link)]]), disable_web_page_preview=True)
    except Exception as e: await prog.edit(f"❌ Error: {e}")

@bot.on_message(filters.chat(Config.STORAGE_CHANNEL) & (filters.document | filters.video | filters.audio))
async def channel_file(client, message):
    if message.from_user and message.from_user.is_self: return
    media = message.document or message.video or message.audio
    uid = secrets.token_urlsafe(8)
    await db.save_link(uid, message.id)
    link = f"{Config.BASE_URL}/show/{uid}"
    await message.reply(f"✅ **Link Generated!**\n📄 `{media.file_name or 'Unknown'}`\n🔗 `{link}`", disable_web_page_preview=True)

@app.api_route("/", methods=["GET","HEAD"])
async def home(): return JSONResponse({"status":"ok"})

@app.get("/show/{uid}", response_class=HTMLResponse)
async def show(request: Request, uid: str):
    mid = await db.get_link(uid)
    if not mid: raise HTTPException(404)
    try:
        msg = await bot.get_messages(Config.STORAGE_CHANNEL, mid)
        m = msg.document or msg.video or msg.audio
        safe = "".join(c for c in (m.file_name or "file") if c.isalnum() or c in (' ','.','_','-')).rstrip()
        return templates.TemplateResponse("show.html", {"request":request, "file_name":m.file_name, "file_size":get_readable_file_size(m.file_size), "is_media":(m.mime_type or "").startswith(("video/","audio/")), "direct_dl_link":f"{Config.BASE_URL}/dl/{mid}/{safe}"})
    except: raise HTTPException(404)

@app.get("/api/file/{uid}")
async def api_file(uid: str):
    mid = await db.get_link(uid)
    if not mid: raise HTTPException(404)
    msg = await bot.get_messages(Config.STORAGE_CHANNEL, mid)
    m = msg.document or msg.video or msg.audio
    safe = "".join(c for c in (m.file_name or "file") if c.isalnum() or c in (' ','.','_','-')).rstrip()
    return JSONResponse({"file_name":m.file_name, "file_size":get_readable_file_size(m.file_size), "mime_type":m.mime_type, "is_media":(m.mime_type or "").startswith(("video/","audio/")), "direct_dl_link":f"{Config.BASE_URL}/dl/{mid}/{safe}"})

@app.get("/dl/{mid}/{fname}")
async def download(mid: int, fname: str, request: Request):
    try:
        msg = await bot.get_messages(Config.STORAGE_CHANNEL, mid)
        m = msg.document or msg.video or msg.audio
        if not m: raise HTTPException(404)
        fid = FileId.decode(m.file_id)
        fsize = m.file_size
        rh = request.headers.get("Range","")
        fb, ub = 0, fsize-1
        if rh:
            p = rh.replace("bytes=","").split("-")
            fb = int(p[0])
            if p[1]: ub = int(p[1])
        cs = 1024*1024
        off = (fb//cs)*cs
        fc = fb - off
        lc = (ub%cs)+1
        pc = math.ceil((ub-fb+1)/cs)
        async def stream():
            loc = raw.types.InputDocumentFileLocation(id=fid.media_id, access_hash=fid.access_hash, file_reference=fid.file_reference, thumb_size="")
            cur = off
            for i in range(pc):
                try:
                    r = await bot.invoke(raw.functions.upload.GetFile(location=loc, offset=cur, limit=cs))
                    if isinstance(r, raw.types.upload.File):
                        if pc==1: yield r.bytes[fc:lc]
                        elif i==0: yield r.bytes[fc:]
                        elif i==pc-1: yield r.bytes[:lc]
                        else: yield r.bytes
                        cur += cs
                except FloodWait as e: await asyncio.sleep(e.value)
                except: break
        hdrs = {"Content-Type":m.mime_type or "application/octet-stream","Accept-Ranges":"bytes","Content-Disposition":f'inline; filename="{m.file_name}"',"Content-Length":str(ub-fb+1)}
        if rh: hdrs["Content-Range"] = f"bytes {fb}-{ub}/{fsize}"
        return StreamingResponse(stream(), status_code=206 if rh else 200, headers=hdrs)
    except HTTPException: raise
    except Exception as e: raise HTTPException(500)

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return HTMLResponse(content="""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Upload - PlayFlx</title><script src="https://cdn.tailwindcss.com"></script><style>body{background:#0a0a0a;color:white;font-family:system-ui}.upload-box{border:2px dashed #6366f1;border-radius:16px;padding:40px;text-align:center;cursor:pointer}.upload-box:hover{border-color:#818cf8;background:rgba(99,102,241,.05)}.btn{background:#6366f1;color:white;padding:12px 30px;border-radius:8px;font-weight:600;cursor:pointer;border:none}.btn:hover{background:#4f46e5}.link-input{background:#1a1a1a;border:1px solid #333;color:white;padding:12px;border-radius:8px;width:100%;font-family:monospace}</style></head><body class="min-h-screen flex flex-col"><header class="p-6 text-center"><h1 class="text-3xl font-bold text-indigo-400">📤 PlayFlx Upload</h1></header><main class="flex-grow flex items-center justify-center px-4"><div class="max-w-xl w-full"><div class="upload-box" id="dropZone"><p class="text-5xl mb-4">📁</p><p class="text-xl font-semibold">Drop file or click to upload</p><input type="file" id="fileInput" class="hidden" onchange="uploadFile()"></div><div id="progress" class="mt-4 text-center" style="display:none"><div class="bg-gray-800 rounded-full h-4 mb-2"><div id="progressBar" class="bg-indigo-500 h-4 rounded-full" style="width:0%"></div></div><p id="progressText" class="text-gray-400">Uploading...</p></div><div id="result" class="mt-6 bg-gray-900 rounded-xl p-6" style="display:none"><p class="text-green-400 font-semibold mb-3">✅ Upload Complete!</p><div class="flex gap-2 mt-1"><input type="text" id="linkInput" class="link-input" readonly><button class="btn" onclick="copyLink()">Copy</button></div><div class="flex gap-2 mt-3"><a id="openLink" href="#" target="_blank" class="btn text-center flex-1">Open</a><button class="btn" onclick="location.reload()" style="background:#333">Upload More</button></div></div></div></main><script>const dropZone=document.getElementById('dropZone'),fileInput=document.getElementById('fileInput'),progress=document.getElementById('progress'),result=document.getElementById('result'),progressBar=document.getElementById('progressBar'),progressText=document.getElementById('progressText'),linkInput=document.getElementById('linkInput'),openLink=document.getElementById('openLink');dropZone.addEventListener('click',()=>fileInput.click());dropZone.addEventListener('dragover',e=>{e.preventDefault();dropZone.style.borderColor='#818cf8'});dropZone.addEventListener('dragleave',()=>{dropZone.style.borderColor='#6366f1'});dropZone.addEventListener('drop',e=>{e.preventDefault();dropZone.style.borderColor='#6366f1';if(e.dataTransfer.files.length){fileInput.files=e.dataTransfer.files;uploadFile()}});async function uploadFile(){const file=fileInput.files[0];if(!file)return;const formData=new FormData();formData.append('file',file);result.style.display='none';progress.style.display='block';dropZone.style.display='none';const xhr=new XMLHttpRequest();xhr.upload.addEventListener('progress',e=>{if(e.lengthComputable){const p=Math.round((e.loaded/e.total)*100);progressBar.style.width=p+'%';progressText.textContent='Uploading... '+p+'%'}});xhr.addEventListener('load',()=>{progress.style.display='none';if(xhr.status===200){const data=JSON.parse(xhr.responseText);linkInput.value=data.link;openLink.href=data.link;result.style.display='block'}else{alert('Upload failed!');dropZone.style.display='block'}});xhr.addEventListener('error',()=>{progress.style.display='none';dropZone.style.display='block';alert('Error!')});xhr.open('POST','/upload/file');xhr.send(formData)}function copyLink(){linkInput.select();document.execCommand('copy');alert('✅ Copied!')}</script></body></html>""")

@app.post("/upload/file")
async def upload_api(file: UploadFile = File(...)):
    try:
        temp = f"/tmp/{uuid.uuid4()}_{file.filename}"
        with open(temp,"wb") as f: shutil.copyfileobj(file.file, f)
        sent = await bot.send_document(Config.STORAGE_CHANNEL, temp, file_name=file.filename)
        os.remove(temp)
        uid = secrets.token_urlsafe(8)
        await db.save_link(uid, sent.id)
        return JSONResponse({"success":True,"link":f"{Config.BASE_URL}/show/{uid}"})
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.get("/files", response_class=HTMLResponse)
async def files_gallery(request: Request):
    try:
        msgs = []
        async for m in bot.get_chat_history(Config.STORAGE_CHANNEL, limit=100):
            if m.document or m.video or m.audio: msgs.append(m)
        if not msgs: return HTMLResponse("<html><head><link href='https://cdn.jsdelivr.net/npm/bootswatch@5.0.0/dist/darkly/bootstrap.min.css' rel='stylesheet'></head><body class='text-center mt-5 text-white bg-dark'><h1>📂 No files!</h1><a href='/upload' class='btn btn-primary mt-3'>Upload</a></body></html>")
        cards = ""
        for m in msgs:
            media = m.document or m.video or m.audio
            fn = media.file_name or "Unknown"
            fs = get_readable_file_size(media.file_size) if media.file_size else "N/A"
            mt = media.mime_type or ""
            icon = "🎬" if mt.startswith("video/") else "🎵" if mt.startswith("audio/") else "📄"
            uid = secrets.token_urlsafe(8)
            await db.save_link(uid, m.id)
            show = f"{Config.BASE_URL}/show/{uid}"
            dl = f"{Config.BASE_URL}/dl/{m.id}/{fn}"
            cards += f"""<div class="col-lg-3 col-md-4 col-sm-6 mb-4"><div class="card bg-dark border-secondary h-100"><div class="card-img-top d-flex align-items-center justify-content-center" style="height:160px;background:#111;font-size:50px;">{icon}</div><div class="card-body"><h6 class="card-title text-truncate" title="{fn}">{fn}</h6><p class="card-text small text-muted">📦 {fs}</p><a href="{show}" class="btn btn-sm btn-primary" target="_blank">👁 View</a><a href="{dl}" class="btn btn-sm btn-success">⬇ DL</a><button class="btn btn-sm btn-secondary" onclick="navigator.clipboard.writeText('{dl}');alert('✅ Copied!')">📋</button></div></div></div>"""
        return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Files - PlayFlx</title><link href="https://cdn.jsdelivr.net/npm/bootswatch@5.0.0/dist/darkly/bootstrap.min.css" rel="stylesheet"><style>body{{background:#0a0a0a;color:white}}.navbar{{background:#1a1a1a!important;border-bottom:2px solid #6366f1}}.card{{transition:transform .3s,box-shadow .3s}}.card:hover{{transform:translateY(-5px);box-shadow:0 10px 30px rgba(99,102,241,.3)}}</style></head><body><nav class="navbar navbar-expand-lg sticky-top"><div class="container-fluid"><a class="navbar-brand" href="/" style="color:#6366f1!important;font-weight:bold">📂 PlayFlx Files</a><span class="navbar-text text-light">📹 {len(msgs)} files</span><a href="/upload" class="btn btn-primary btn-sm">📤 Upload</a></div></nav><div class="container py-4"><h1 class="mb-4">📁 All Files</h1><div class="row">{cards}</div></div></body></html>""")
    except Exception as e: raise HTTPException(500)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT",10000)), log_level="info")