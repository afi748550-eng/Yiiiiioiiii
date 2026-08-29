import os
import sys
import shutil
import asyncio
import logging
import zipfile
import json
import psutil
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# ----------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------
# مقادیر توکن و آیدی عددی خود را در دو متغیر زیر قرار دهید:
DEFAULT_BOT_TOKEN = "8375377585:AAFsGrEmJLnGuSE-rnoeHMJ7_m71XqOr4yc"
DEFAULT_ADMIN_ID = 7764565509  # آیدی عددی تلگرام خود را اینجا بگذارید

BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN)
ADMIN_ID = int(os.getenv("ADMIN_ID", DEFAULT_ADMIN_ID))
DB_FILE = "running_db.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RUNNING_PROCESSES = {}

# ----------------------------------------------------
# DATABASE HELPERS
# ----------------------------------------------------
def save_db():
    data = {}
    for pid, info in RUNNING_PROCESSES.items():
        data[str(pid)] = {
            "file_name": info["file_name"],
            "work_dir": info["work_dir"],
            "user_id": info["user_id"],
            "end_time": info["end_time"].strftime('%Y-%m-%d %H:%M:%S')
        }
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ----------------------------------------------------
# STATES
# ----------------------------------------------------
class UploadState(StatesGroup):
    waiting_for_file = State()
    waiting_for_duration_unit = State()
    waiting_for_duration_value = State()

class ProjectManageState(StatesGroup):
    waiting_for_project_selection = State()
    waiting_for_action = State()
    waiting_for_extend_time = State()

# ----------------------------------------------------
# KEYBOARDS (Color Buttons with Bot API 8.0 Styles)
# ----------------------------------------------------
def get_main_keyboard():
    buttons = [
        [KeyboardButton(text="📤 Upload & Run Project", style="primary")],
        [KeyboardButton(text="📁 My Projects", style="primary"), KeyboardButton(text="🖥 Server Status", style="primary")],
        [KeyboardButton(text="📖 Tutorial", style="success")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel", style="danger")]],
        resize_keyboard=True
    )

def get_time_unit_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏱ Hours", style="primary"), KeyboardButton(text="📅 Days", style="success")],
            [KeyboardButton(text="❌ Cancel", style="danger")]
        ],
        resize_keyboard=True
    )

# Admin Access Middleware
@dp.message.outer_middleware()
async def admin_only_middleware(handler, event: types.Message, data):
    if event.from_user.id != ADMIN_ID:
        await event.answer("⛔ Access Denied! This bot is private.")
        return
    return await handler(event, data)

# ----------------------------------------------------
# COMMANDS & HANDLERS
# ----------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 **Welcome Boss!**\n\nYour code runner bot is online and ready.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "❌ Cancel")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Operation canceled.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📖 Tutorial")
async def show_tutorial(message: types.Message):
    tutorial_text = (
        "📚 **Code Runner Tutorial**\n\n"
        "• **Supported Languages:** Python (`.py`), Node.js (`.js`), TypeScript (`.ts`), Go (`.go`), Java (`.java`), PHP (`.php`), Rust (`.rs`)\n"
        "• **ZIP Packages:** Upload `.zip` files for multi-file projects.\n"
        "• **Auto Libraries:** Include `requirements.txt` or `package.json` inside your ZIP for automatic dependency installation in terminal."
    )
    await message.answer(tutorial_text, parse_mode="Markdown")

@dp.message(F.text == "🖥 Server Status")
async def server_status(message: types.Message):
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    status_msg = (
        "🖥 **Detailed Server Status**\n\n"
        f"💻 **CPU Usage:** `{cpu}%`\n"
        f"🧠 **RAM Used:** `{ram.used // (1024**2)} MB` / `{ram.total // (1024**2)} MB` (`{ram.percent}%`)\n"
        f"🧠 **RAM Free:** `{ram.available // (1024**2)} MB`\n"
        f"💾 **Disk Free:** `{disk.free // (1024**3)} GB`\n"
        f"⚙️ **Active Projects:** `{len(RUNNING_PROCESSES)}`"
    )
    await message.answer(status_msg, parse_mode="Markdown")

# ----------------------------------------------------
# UPLOAD & EXECUTION
# ----------------------------------------------------
@dp.message(F.text == "📤 Upload & Run Project")
async def start_upload(message: types.Message, state: FSMContext):
    await state.set_state(UploadState.waiting_for_file)
    await message.answer("📥 Send your project file or ZIP archive:", reply_markup=get_cancel_keyboard())

@dp.message(UploadState.waiting_for_file, F.document)
async def handle_file(message: types.Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name
    ext = os.path.splitext(file_name)[1].lower()
    allowed_exts = ['.py', '.js', '.ts', '.go', '.java', '.php', '.rs', '.zip']
    
    if ext not in allowed_exts:
        await message.answer("❌ Unsupported file extension!")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = os.path.join(os.getcwd(), f"run_{message.from_user.id}_{timestamp}")
    os.makedirs(work_dir, exist_ok=True)
    
    file_path = os.path.join(work_dir, file_name)
    await bot.download(doc, destination=file_path)

    if ext == '.zip':
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(work_dir)
            os.remove(file_path)
        except Exception as e:
            shutil.rmtree(work_dir, ignore_errors=True)
            await message.answer(f"❌ Zip extraction failed: `{str(e)}`", parse_mode="Markdown")
            await state.clear()
            return

    await state.update_data(work_dir=work_dir, file_name=file_name, ext=ext)
    await state.set_state(UploadState.waiting_for_duration_unit)
    await message.answer("⏰ Select runtime unit:", reply_markup=get_time_unit_keyboard())

@dp.message(UploadState.waiting_for_duration_unit, F.text.in_(["⏱ Hours", "📅 Days"]))
async def select_duration_unit(message: types.Message, state: FSMContext):
    unit = "hours" if "Hours" in message.text else "days"
    await state.update_data(time_unit=unit)
    await state.set_state(UploadState.waiting_for_duration_value)
    await message.answer(f"⌛ Enter runtime duration in **{unit.capitalize()}**:", reply_markup=get_cancel_keyboard())

@dp.message(UploadState.waiting_for_duration_value)
async def run_project_final(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Send a valid positive integer.")
        return

    duration_val = int(message.text)
    data = await state.get_data()
    work_dir, file_name, ext, unit = data["work_dir"], data["file_name"], data["ext"], data["time_unit"]

    duration_seconds = duration_val * 3600 if unit == "hours" else duration_val * 86400
    end_time = datetime.now() + timedelta(seconds=duration_seconds)

    await message.answer("⚙️ Installing packages and preparing runtime...")

    req_txt = os.path.join(work_dir, "requirements.txt")
    pkg_json = os.path.join(work_dir, "package.json")
    
    if os.path.exists(req_txt):
        proc = await asyncio.create_subprocess_exec("pip", "install", "-r", "requirements.txt", cwd=work_dir)
        await proc.wait()
    if os.path.exists(pkg_json):
        proc = await asyncio.create_subprocess_exec("npm", "install", cwd=work_dir)
        await proc.wait()

    cmd = []
    if ext == '.py' or os.path.exists(os.path.join(work_dir, "main.py")):
        target = "main.py" if ext == '.zip' else file_name
        cmd = [sys.executable, target]
    elif ext == '.js' or os.path.exists(os.path.join(work_dir, "index.js")):
        target = "index.js" if ext == '.zip' else file_name
        cmd = ["node", target]
    elif ext == '.ts': cmd = ["npx", "ts-node", file_name]
    elif ext == '.go': cmd = ["go", "run", file_name]
    elif ext == '.php': cmd = ["php", file_name]
    elif ext == '.java': cmd = ["java", file_name]
    elif ext == '.rs': cmd = ["rustc", file_name, "-o", "app"]

    try:
        process = await asyncio.create_subprocess_exec(*cmd, cwd=work_dir)
        pid = process.pid
        
        task = asyncio.create_task(auto_stop_project(pid, duration_seconds, file_name, work_dir))
        
        RUNNING_PROCESSES[pid] = {
            "process": process,
            "file_name": file_name,
            "work_dir": work_dir,
            "user_id": message.from_user.id,
            "end_time": end_time,
            "task": task
        }
        save_db()

        await message.answer(
            f"🚀 **Project is now Running!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"🆔 **PID:** `{pid}`\n"
            f"📅 **Expires At:** `{end_time.strftime('%Y-%m-%d %H:%M:%S')}`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        await message.answer(f"❌ Execution Error: `{str(e)}`", parse_mode="Markdown", reply_markup=get_main_keyboard())

    await state.clear()

async def auto_stop_project(pid, delay, file_name, work_dir):
    await asyncio.sleep(delay)
    if pid in RUNNING_PROCESSES:
        p_info = RUNNING_PROCESSES[pid]
        try:
            p_info["process"].terminate()
            await p_info["process"].wait()
        except Exception: pass
        
        shutil.rmtree(work_dir, ignore_errors=True)
        del RUNNING_PROCESSES[pid]
        save_db()
        
        try:
            await bot.send_message(ADMIN_ID, f"⏰ **Time Expired!** Project `{file_name}` (PID: `{pid}`) was automatically stopped.")
        except Exception: pass

# ----------------------------------------------------
# PROJECT MANAGEMENT
# ----------------------------------------------------
@dp.message(F.text == "📁 My Projects")
async def my_projects(message: types.Message, state: FSMContext):
    if not RUNNING_PROCESSES:
        await message.answer("ℹ️ No active projects currently running.")
        return

    text = "📁 **Active Projects:**\n\n"
    buttons = []
    for pid, info in RUNNING_PROCESSES.items():
        rem = info["end_time"] - datetime.now()
        mins = max(0, int(rem.total_seconds() // 60))
        text += f"🔹 **PID:** `{pid}` | `{info['file_name']}` | Remaining: `{mins}m`\n"
        buttons.append([KeyboardButton(text=f"Manage PID {pid}", style="primary")])

    buttons.append([KeyboardButton(text="❌ Cancel", style="danger")])
    await state.set_state(ProjectManageState.waiting_for_project_selection)
    await message.answer(text, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))

@dp.message(ProjectManageState.waiting_for_project_selection, F.text.startswith("Manage PID "))
async def select_project(message: types.Message, state: FSMContext):
    pid = int(message.text.replace("Manage PID ", ""))
    if pid not in RUNNING_PROCESSES:
        await message.answer("❌ Project not found.")
        await state.clear()
        return

    await state.update_data(selected_pid=pid)
    await state.set_state(ProjectManageState.waiting_for_action)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛑 Stop & Delete", style="danger")],
            [KeyboardButton(text="➕ Extend Time", style="success")],
            [KeyboardButton(text="❌ Cancel", style="primary")]
        ],
        resize_keyboard=True
    )
    await message.answer(f"⚙️ Action for PID `{pid}`:", parse_mode="Markdown", reply_markup=keyboard)

@dp.message(ProjectManageState.waiting_for_action, F.text == "🛑 Stop & Delete")
async def stop_project_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("selected_pid")
    
    if pid in RUNNING_PROCESSES:
        p_info = RUNNING_PROCESSES[pid]
        p_info["task"].cancel()
        try: p_info["process"].terminate()
        except Exception: pass
        shutil.rmtree(p_info["work_dir"], ignore_errors=True)
        del RUNNING_PROCESSES[pid]
        save_db()
        await message.answer(f"✅ PID `{pid}` stopped.", reply_markup=get_main_keyboard())
    
    await state.clear()

@dp.message(ProjectManageState.waiting_for_action, F.text == "➕ Extend Time")
async def extend_time_prompt(message: types.Message, state: FSMContext):
    await state.set_state(ProjectManageState.waiting_for_extend_time)
    await message.answer("⌛ Enter extra hours to add:", reply_markup=get_cancel_keyboard())

@dp.message(ProjectManageState.waiting_for_extend_time)
async def extend_time_action(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Enter a valid number.")
        return

    extra_hours = int(message.text)
    data = await state.get_data()
    pid = data.get("selected_pid")

    if pid in RUNNING_PROCESSES:
        p_info = RUNNING_PROCESSES[pid]
        p_info["end_time"] += timedelta(hours=extra_hours)
        p_info["task"].cancel()
        rem_seconds = (p_info["end_time"] - datetime.now()).total_seconds()
        p_info["task"] = asyncio.create_task(auto_stop_project(pid, rem_seconds, p_info["file_name"], p_info["work_dir"]))
        save_db()
        await message.answer(f"✅ Extended! Expiry: `{p_info['end_time'].strftime('%Y-%m-%d %H:%M:%S')}`", parse_mode="Markdown", reply_markup=get_main_keyboard())

    await state.clear()

# ----------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
