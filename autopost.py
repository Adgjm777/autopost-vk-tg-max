#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автопостинг медиа: VK (сообщество) + Telegram + Max.

- Берёт СЛУЧАЙНЫЙ файл из папки MEDIA_DIR, публикует и УДАЛЯЕТ его после успеха.
- Если папка пуста — просто ждёт пополнения (ничего не постит).
- VK умеет: опубликовать СРАЗУ или создать ОТЛОЖЕННЫЙ пост (--scheduled --delay минуты).

VK-логика (проверено 2026-11-14):
- ФОТО и публикация на стену: ключ СООБЩЕСТВА (VK_TOKEN).
  фото -> photos.getMessagesUploadServer(group_id) -> upload -> photos.saveMessagesPhoto -> attach
  посты -> wall.post (owner_id=-group, from_group=1)
- ВИДЕО: нужен USER-токен (VK_USER_TOKEN) только для video.save (ключ сообщества video.save не принимает).
  video.save(group_id) -> upload -> attach video-<group>_<id>, а wall.post всё равно делается ключом сообщества.

Примеры запуска:
  python3 autopost.py                     # опубликовать сразу (1 случайный файл)
  python3 autopost.py --scheduled --delay 180   # отложенный пост VK на ~3 часа
  python3 autopost.py --count 3           # сразу 3 файла с паузами
"""
import os, sys, time, random, logging, argparse, datetime, json
import requests

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
# --- загрузка настроек из файла .env рядом со скриптом (если он есть) ---
def _load_env_file(path):
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env_file(os.path.join(BASE_DIR, ".env"))
TOKENS_FILE = os.getenv("TOKENS_FILE", os.path.join(BASE_DIR, "tokens.txt"))   # файл с VK-токенами (или задайте переменные окружения)
MEDIA_DIR  = os.path.join(BASE_DIR, "media")          # папка с медиафайлами
LOG_FILE   = os.path.join(BASE_DIR, "autopost.log")
GROUP_ID   = int(os.getenv("VK_GROUP_ID", "0") or 0)

# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL   = os.getenv("TELEGRAM_CHANNEL", "")
SEND_TELEGRAM      = bool(TELEGRAM_BOT_TOKEN) and bool(TELEGRAM_CHANNEL)

# ---------- Max ----------
MAX_TOKEN = os.getenv("MAX_TOKEN", "")
MAX_CHANNEL_ID = int(os.getenv("MAX_CHANNEL_ID", "0") or 0)
MAX_API_BASE   = "https://platform-api.max.ru"
SEND_MAX       = bool(MAX_TOKEN) and bool(MAX_CHANNEL_ID)

VIDEO_EXT = ('mp4','mov','avi','mkv','webm','wmv','mpeg','mpg','3gp','m4v')
IMAGE_EXT = ('jpg','jpeg','png','gif','webp','bmp','heic')
ALL_EXT   = VIDEO_EXT + IMAGE_EXT
PAUSE_MIN, PAUSE_MAX = 90, 150          # пауза между постами в одной серии
VIDEO_WAIT_SEC = 120                    # ожидание обработки видео на стороне VK

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger().addHandler(logging.StreamHandler())

# ---------- тексты ----------
HASHTAGS = ["#юмор","#животные","#коты","#собаки","#мемы","#приколы","#hihichpock","#питомцы",
            "#милота","#видеодня","#топ","#смешныеживотные","#котик","#семья","#любимыепитомцы",
            "#позитив","#тренды","#интересное","#домашниеживотные","#котики","#щенок"]
EMOJI = ["🔥","😂","😍","🤯","🐱","🐶","✨","❤️","😳","👀","🎉","💯","😊","🐾","🎬"]
DESC = ["Это выйдет за рамки воображения… 🤯","Такого ты ещё не видел(а)! 👀","Это покорит твоё сердце ❤️",
        "Смотри и удивляйся! 😱","Готов(а) к сюрпризу? 🎉","Это просто невероятно! 🔥"]

def make_caption():
    parts = []
    if random.random() > 0.2:
        parts.append(random.choice(DESC) if random.random() < 0.5 else random.choice(EMOJI))
    parts.append(" ".join(random.sample(HASHTAGS, 7)))
    return "\n".join([p for p in parts if p])

# ---------- VK ----------
VK_API = "https://api.vk.com/method/"
VK_VER = "5.199"

def read_tokens():
    tokens = {}
    try:
        for line in open(TOKENS_FILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            tokens[k.strip()] = v.strip()
    except Exception as e:
        logging.error("Не читаются токены %s: %s", TOKENS_FILE, e)
    for _k in ("VK_TOKEN", "VK_USER_TOKEN"):
        if os.getenv(_k):
            tokens[_k] = os.getenv(_k)
    return tokens

RETRY_CODES = (6, 10, 1051)   # временные/edge-ошибки VK: пробуем ещё раз

def vk_call(method, token, _retries=3, **params):
    params["access_token"] = token
    params["v"] = VK_VER
    last = None
    for attempt in range(_retries):
        r = requests.post(VK_API + method, data=params, timeout=300)
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            last = err
            code = err.get("error_code")
            if code in RETRY_CODES and attempt < _retries - 1:
                logging.warning("VK %s: [%s] %s — повтор через 10 сек (попытка %s)", method, code, err.get("error_msg"), attempt + 1)
                time.sleep(10)
                continue
            raise RuntimeError("VK %s: [%s] %s" % (method, code, err.get("error_msg")))
        return data.get("response")
    raise RuntimeError("VK %s: %s" % (method, last))

def vk_upload_photo(group_token, path):
    """Загрузка фото в сообщество (через сервер загрузки сообщений) ключом сообщества."""
    up = vk_call("photos.getMessagesUploadServer", group_token, group_id=GROUP_ID)
    url = up.get("upload_url")
    if not url:
        raise RuntimeError("photos.getMessagesUploadServer не вернул upload_url")
    with open(path, "rb") as f:
        r = requests.post(url, files={"photo": (os.path.basename(path), f)}, timeout=900)
    if not r.ok:
        raise RuntimeError("загрузка фото: HTTP %s" % r.status_code)
    j = r.json()
    saved = vk_call("photos.saveMessagesPhoto", group_token,
                    server=j["server"], photo=j["photo"], hash=j["hash"])
    p = saved[0]
    return "photo{}_{}".format(p["owner_id"], p["id"])

def vk_upload_video(user_token, path):
    """Загрузка видео в сообщество. video.save принимает ТОЛЬКО user-токен."""
    fname = os.path.basename(path)
    save = vk_call("video.save", user_token, name="Clip_" + fname[:25], group_id=GROUP_ID,
                   is_private=0, wallpost=0, repeat=0)
    url = save.get("upload_url"); owner_id = save.get("owner_id"); vid = save.get("video_id")
    if not url or owner_id is None or vid is None:
        raise RuntimeError("video.save вернул некорректный ответ")
    with open(path, "rb") as f:
        r = requests.post(url, files={"video_file": (fname, f, "video/mp4")}, timeout=900)
    if not r.ok:
        raise RuntimeError("загрузка видео: HTTP %s" % r.status_code)
    logging.info("VK: видео загружено, ждём обработки %s сек", VIDEO_WAIT_SEC)
    time.sleep(VIDEO_WAIT_SEC)
    return "video{}_{}".format(owner_id, vid)

def vk_publish(tokens, path, caption, publish_ts=None):
    group_token = tokens.get("VK_TOKEN", "")
    user_token  = tokens.get("VK_USER_TOKEN", "")
    if not group_token:
        raise RuntimeError("нет VK_TOKEN (ключ сообщества) в %s" % TOKENS_FILE)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in VIDEO_EXT:
        if not user_token:
            raise RuntimeError("для видео нужен VK_USER_TOKEN (user-токен для video.save)")
        attachment = vk_upload_video(user_token, path)
    else:
        attachment = vk_upload_photo(group_token, path)
    params = dict(owner_id=-GROUP_ID, from_group=1, message=caption,
                  attachments=attachment, signed=0, mark_as_ads=0, close_comments=0)
    if publish_ts:
        params["publish_date"] = int(publish_ts)
    res = vk_call("wall.post", group_token, **params)
    if res and res.get("post_id"):
        link = "https://vk.com/wall-{}_{}".format(GROUP_ID, res["post_id"])
        logging.info("VK: %s", "ОТЛОЖЕН на %s" % datetime.datetime.fromtimestamp(publish_ts) if publish_ts else ("ОПУБЛИКОВАНО " + link))
        return True
    logging.error("VK: wall.post не вернул post_id: %s", res)
    return False

# ---------- Telegram ----------
def post_to_telegram(path, caption):
    if not SEND_TELEGRAM or not TELEGRAM_BOT_TOKEN:
        return False
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    cap = (caption or "")[:1024]
    fname = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            if ext in VIDEO_EXT:
                r = requests.post("https://api.telegram.org/bot%s/sendVideo" % TELEGRAM_BOT_TOKEN,
                                  data={"chat_id": TELEGRAM_CHANNEL, "caption": cap, "supports_streaming": "true"},
                                  files={"video": (fname, f, "video/mp4")}, timeout=900)
            else:
                r = requests.post("https://api.telegram.org/bot%s/sendPhoto" % TELEGRAM_BOT_TOKEN,
                                  data={"chat_id": TELEGRAM_CHANNEL, "caption": cap},
                                  files={"photo": (fname, f)}, timeout=180)
        ok = r.ok and r.json().get("ok")
        logging.info("Telegram: %s", "OK" if ok else "ошибка %s %s" % (r.status_code, r.text[:200]))
        return bool(ok)
    except Exception as e:
        logging.error("Telegram: %s", e)
        return False

# ---------- Max ----------
def post_to_max(path, caption):
    if not SEND_MAX or not MAX_TOKEN:
        return False
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mtype = "video" if ext in VIDEO_EXT else "image"
    h = {"Authorization": MAX_TOKEN}
    try:
        r = requests.post("%s/uploads" % MAX_API_BASE, params={"type": mtype}, headers=h, timeout=30)
        if not r.ok:
            logging.error("Max upload url: %s %s", r.status_code, r.text[:200]); return False
        d = r.json(); up = d.get("url"); token = d.get("token")
        if not up:
            logging.error("Max: нет url %s", d); return False
        fname = os.path.basename(path)
        with open(path, "rb") as f:
            r2 = requests.post(up, headers=h, files={"data": (fname, f.read(), "video/mp4" if mtype=="video" else "image/jpeg")}, timeout=600)
        if not r2.ok:
            logging.error("Max upload file: %s %s", r2.status_code, r2.text[:200]); return False
        try:
            token = token or r2.json().get("token")
        except Exception:
            pass
        time.sleep(5)
        r3 = requests.post("%s/messages" % MAX_API_BASE, params={"chat_id": MAX_CHANNEL_ID},
                           headers={**h, "Content-Type": "application/json"},
                           json={"text": (caption or "")[:4000], "attachments":[{"type": mtype, "payload":{"token": token}}]},
                           timeout=30)
        ok = r3.ok
        logging.info("Max: %s", "OK" if ok else "ошибка %s %s" % (r3.status_code, r3.text[:200]))
        return bool(ok)
    except Exception as e:
        logging.error("Max: %s", e)
        return False

# ---------- логика ----------
def list_media():
    if not os.path.isdir(MEDIA_DIR):
        os.makedirs(MEDIA_DIR, exist_ok=True)
        return []
    out = []
    for f in os.listdir(MEDIA_DIR):
        fp = os.path.join(MEDIA_DIR, f)
        if not os.path.isfile(fp):
            continue
        if os.path.splitext(f)[0].lower().endswith("_thumb"):
            continue
        if os.path.splitext(f)[1].lower().lstrip(".") in ALL_EXT:
            out.append(f)
    return out

STATE_FILE = os.path.join(BASE_DIR, ".last_media_type")

def _last_type():
    try:
        return (open(STATE_FILE).read() or "").strip()
    except Exception:
        return ""

def _set_last_type(t):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(t)
    except Exception:
        pass

def choose_media(files):
    """Чтобы фото и видео шли вперемешку: по возможности берём тип, обратный прошлому посту."""
    vids = [f for f in files if os.path.splitext(f)[1].lower().lstrip(".") in VIDEO_EXT]
    imgs = [f for f in files if os.path.splitext(f)[1].lower().lstrip(".") in IMAGE_EXT]
    last = _last_type()
    if last == "video" and imgs:
        fname = random.choice(imgs)
    elif last == "image" and vids:
        fname = random.choice(vids)
    elif vids and imgs:
        fname = random.choice(vids if random.random() < 0.5 else imgs)
    else:
        fname = random.choice(files)
    mtype = "video" if os.path.splitext(fname)[1].lower().lstrip(".") in VIDEO_EXT else "image"
    return fname, mtype

POSTED_STATE = os.path.join(BASE_DIR, ".posted_state.json")

def _load_posted():
    try:
        return json.load(open(POSTED_STATE, encoding="utf-8"))
    except Exception:
        return {}

def _save_posted(d):
    try:
        json.dump(d, open(POSTED_STATE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def publish_one(tokens, fname, publish_ts=None):
    path = os.path.join(MEDIA_DIR, fname)
    if not os.path.exists(path):
        logging.warning("Файл не найден: %s", fname); return False
    caption = make_caption()
    state = _load_posted().get(fname, {})

    ok_vk = False
    try:
        ok_vk = vk_publish(tokens, path, caption, publish_ts=publish_ts)
    except Exception as e:
        logging.error("VK ошибка [%s]: %s", fname, e)

    # Telegram и Max шлём один раз на файл, чтобы не дублировать, пока VK не принял
    if not state.get("tg"):
        try:
            if post_to_telegram(path, caption):
                state["tg"] = True
        except Exception as e:
            logging.error("Telegram [%s]: %s", fname, e)
    if not state.get("max"):
        try:
            if post_to_max(path, caption):
                state["max"] = True
        except Exception as e:
            logging.error("Max [%s]: %s", fname, e)

    allstate = _load_posted()
    if ok_vk:
        try:
            os.remove(path)
            logging.info("Файл %s удалён после публикации", fname)
        except OSError as e:
            logging.error("Не удалось удалить %s: %s", fname, e)
        allstate.pop(fname, None)
    else:
        allstate[fname] = state
        logging.info("Файл %s сохранён (VK не принял) — TG/Max уже отправлены, повторять не будем", fname)
    _save_posted(allstate)
    return ok_vk

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheduled", action="store_true", help="создать отложенный пост VK")
    ap.add_argument("--delay", type=int, default=180, help="на сколько минут вперёд отложить (по умолчанию 180)")
    ap.add_argument("--count", type=int, default=1, help="сколько файлов опубликовать за запуск")
    args = ap.parse_args()

    files = list_media()
    if not files:
        logging.info("Папка %s пуста — ждём пополнения.", MEDIA_DIR)
        return 0

    tokens = read_tokens()
    if not tokens.get("VK_TOKEN"):
        logging.error("Нет VK_TOKEN (ключ сообщества) — выход.")
        return 1

    publish_ts = time.time() + args.delay * 60 if args.scheduled else None
    n = min(args.count, len(files))
    remaining = files[:]

    for i in range(n):
        if not remaining:
            break
        fname, mtype = choose_media(remaining)
        logging.info("Выбран %s: %s", mtype, fname)
        if i > 0:
            p = random.randint(PAUSE_MIN, PAUSE_MAX)
            logging.info("Пауза %s сек…", p); time.sleep(p)
        ok = publish_one(tokens, fname, publish_ts=publish_ts)
        if ok:
            _set_last_type(mtype)
        try:
            remaining.remove(fname)
        except ValueError:
            pass
        if publish_ts:
            publish_ts += 15 * 60   # небольшой разнос отложенных
    logging.info("Готово.")
    return 0

if __name__ == "__main__":
    sys.exit(main())