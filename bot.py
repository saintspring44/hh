import logging
import os
import shutil
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_USER_IDS", "").split(",")
    if value.strip().isdigit()
}
DATA_DIR = Path(os.getenv("DATA_DIR", "data")).resolve()
MAX_FILE_SIZE = 10 * 1024 * 1024


def safe_path(raw: str = ".") -> Path:
    candidate = (DATA_DIR / raw).resolve()
    if candidate != DATA_DIR and DATA_DIR not in candidate.parents:
        raise ValueError("Нельзя выходить за пределы папки данных.")
    return candidate


def authorized(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in ADMIN_IDS)


async def guard(update: Update) -> bool:
    if not authorized(update):
        if update.effective_message:
            await update.effective_message.reply_text(
                "Доступ закрыт. Добавьте свой Telegram ID в ADMIN_USER_IDS."
            )
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        "Файловый помощник готов.\n\n"
        "/id — узнать свой Telegram ID\n"
        "/ls [путь] — список файлов\n"
        "/mkdir папка — создать папку\n"
        "/touch файл — создать пустой файл\n"
        "/write файл текст — записать текст\n"
        "/read файл — прочитать файл\n"
        "/get файл — скачать файл\n"
        "/rename старое новое — переименовать\n"
        "/rm файл — удалить файл\n"
        "Также можно отправить мне документ — я сохраню его."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        folder = safe_path(" ".join(context.args) if context.args else ".")
        if not folder.is_dir():
            await update.message.reply_text("Такой папки нет.")
            return
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            await update.message.reply_text("Папка пустая.")
            return
        lines = [("📁 " if p.is_dir() else "📄 ") + p.name for p in entries[:100]]
        await update.message.reply_text("\n".join(lines))
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")


async def mkdir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if not context.args:
            raise ValueError("Укажи имя папки.")
        path = safe_path(" ".join(context.args))
        path.mkdir(parents=True, exist_ok=False)
        await update.message.reply_text(f"Папка создана: {path.relative_to(DATA_DIR)}")
    except Exception as exc:
        await update.message.reply_text(f"Не удалось создать папку: {exc}")


async def touch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if not context.args:
            raise ValueError("Укажи имя файла.")
        path = safe_path(" ".join(context.args))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)
        await update.message.reply_text(f"Файл создан: {path.relative_to(DATA_DIR)}")
    except Exception as exc:
        await update.message.reply_text(f"Не удалось создать файл: {exc}")


async def write_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if len(context.args) < 2:
            raise ValueError("Формат: /write файл.txt текст")
        filename = context.args[0]
        content = " ".join(context.args[1:])
        path = safe_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        await update.message.reply_text(f"Записано в {filename}")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка записи: {exc}")


async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if not context.args:
            raise ValueError("Укажи имя файла.")
        path = safe_path(" ".join(context.args))
        if not path.is_file():
            raise ValueError("Файл не найден.")
        if path.stat().st_size > 50000:
            raise ValueError("Файл больше 50 КБ. Используй /get для скачивания.")
        content = path.read_text(encoding="utf-8")
        await update.message.reply_text(content or "(Файл пуст)")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка чтения: {exc}")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if not context.args:
            raise ValueError("Укажи имя файла.")
        path = safe_path(" ".join(context.args))
        if not path.is_file():
            raise ValueError("Файл не найден.")
        await update.message.reply_document(document=path.open("rb"))
    except Exception as exc:
        await update.message.reply_text(f"Ошибка отправки: {exc}")


async def rename_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if len(context.args) != 2:
            raise ValueError("Формат: /rename старое_имя новое_имя")
        old, new = map(safe_path, context.args)
        if not old.exists():
            raise ValueError("Исходный файл или папка не найдены.")
        if new.exists():
            raise ValueError("Целевой путь уже существует.")
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        await update.message.reply_text("Переименовано.")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")


async def rm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    try:
        if not context.args:
            raise ValueError("Укажи имя файла или пустой папки.")
        path = safe_path(" ".join(context.args))
        if path == DATA_DIR:
            raise ValueError("Нельзя удалить корневую папку данных.")
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
        else:
            raise ValueError("Путь не найден.")
        await update.message.reply_text("Удалено.")
    except Exception as exc:
        await update.message.reply_text(f"Не удалось удалить: {exc}")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    document = update.message.document
    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("Файл слишком большой. Максимум 10 МБ.")
        return
    filename = Path(document.file_name or f"file_{document.file_unique_id}").name
    destination = safe_path(filename)
    if destination.exists():
        await update.message.reply_text("Файл с таким именем уже существует. Переименуй его и отправь снова.")
        return
    try:
        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(destination)
        await update.message.reply_text(f"Файл сохранён: {filename}")
    except Exception as exc:
        log.exception("Document download failed")
        await update.message.reply_text(f"Не удалось сохранить файл: {exc}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN. Создай файл .env или переменную окружения.")
    if not ADMIN_IDS:
        raise RuntimeError("Не задан ADMIN_USER_IDS. Узнай ID командой /id после настройки доступа.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("ls", ls_command))
    app.add_handler(CommandHandler("mkdir", mkdir_command))
    app.add_handler(CommandHandler("touch", touch_command))
    app.add_handler(CommandHandler("write", write_command))
    app.add_handler(CommandHandler("read", read_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("rename", rename_command))
    app.add_handler(CommandHandler("rm", rm_command))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
