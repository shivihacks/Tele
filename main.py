"""Telegram Quiz Bot (python-telegram-bot v21, SQLite, Render-ready).

Secrets come only from environment variables: 9012700166:AAFjyg8pVtLw3ldPfYTqrdTfQ7YDd9rbNBQ, 8868098176.
"""
import asyncio
import hashlib
import html
import json
import logging
import os
import random
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("quizbot")
HTML = ParseMode.HTML

# ───────────────────────────── Configuration ─────────────────────────────


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


TOKEN = _require("BOT_TOKEN")
ADMIN_IDS = {
    int(x) for x in _require("ADMIN_ID").replace(" ", "").split(",") if x.lstrip("-").isdigit()
}
if not ADMIN_IDS:
    raise SystemExit("ADMIN_ID must contain at least one numeric Telegram user ID")

DB_PATH = os.getenv("DB_PATH", "quiz_bot.db")
QUIZ_LENGTH = max(1, int(os.getenv("QUIZ_LENGTH", "5")))
QUESTION_TIME = max(5, int(os.getenv("QUESTION_TIME", "20")))
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

POINTS = {"easy": 10, "medium": 15, "hard": 20}
DCODE = {"easy": "e", "medium": "m", "hard": "h", "mixed": "x"}
DNAME = {v: k for k, v in DCODE.items()}
DEMOJI = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "mixed": "🎲"}
LETTERS = "ABCD"
PAGE_SIZE = 8


def _derive(label: str) -> str:
    return hashlib.sha256(f"{label}:{TOKEN}".encode()).hexdigest()


WEBHOOK_PATH = _derive("path")[:40]
WEBHOOK_SECRET = _derive("secret")

# ───────────────────────────── Seed questions ─────────────────────────────
# (category, difficulty, question, [A, B, C, D], index of correct option)
SEED = [
    ("Science", "easy", "Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Mercury"], 1),
    ("Science", "easy", "Which gas do plants absorb for photosynthesis?", ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], 2),
    ("Science", "medium", "What is the chemical symbol for gold?", ["Ag", "Au", "Gd", "Go"], 1),
    ("Science", "medium", "Which is the hardest natural substance?", ["Gold", "Iron", "Diamond", "Quartz"], 2),
    ("Science", "medium", "What is the powerhouse of the cell?", ["Nucleus", "Mitochondria", "Ribosome", "Golgi apparatus"], 1),
    ("Science", "hard", "Approximate speed of light in vacuum?", ["3,000 km/s", "30,000 km/s", "300,000 km/s", "3,000,000 km/s"], 2),
    ("Science", "hard", "Which blood group is the universal red-cell donor?", ["AB+", "O-", "A-", "B+"], 1),
    ("Technology", "easy", "What does CPU stand for?", ["Central Process Unit", "Central Processing Unit", "Computer Personal Unit", "Core Processing Utility"], 1),
    ("Technology", "easy", "Which company develops the Android OS?", ["Apple", "Google", "Microsoft", "Nokia"], 1),
    ("Technology", "medium", "What does HTML stand for?", ["HyperText Markup Language", "HighText Machine Language", "HyperTool Multi Language", "Home Text Markup Level"], 0),
    ("Technology", "medium", "Which data structure follows LIFO?", ["Queue", "Stack", "Array", "Tree"], 1),
    ("Technology", "medium", "Which keyword defines a function in Python?", ["func", "def", "function", "lambda"], 1),
    ("Technology", "medium", "Which HTTP status code means 'Not Found'?", ["200", "301", "404", "500"], 2),
    ("Technology", "hard", "Time complexity of binary search?", ["O(n)", "O(log n)", "O(n log n)", "O(1)"], 1),
    ("Technology", "hard", "Which SQL clause filters grouped results?", ["WHERE", "HAVING", "GROUP BY", "ORDER BY"], 1),
    ("Geography", "easy", "What is the capital of India?", ["Mumbai", "New Delhi", "Kolkata", "Chennai"], 1),
    ("Geography", "easy", "Which is the largest ocean?", ["Atlantic", "Indian", "Pacific", "Arctic"], 2),
    ("Geography", "medium", "Which is the longest river in Africa?", ["Congo", "Nile", "Niger", "Zambezi"], 1),
    ("Geography", "medium", "What is the capital of Canada?", ["Toronto", "Ottawa", "Vancouver", "Montreal"], 1),
    ("Geography", "medium", "Which is the smallest country by area?", ["Monaco", "Vatican City", "San Marino", "Malta"], 1),
    ("Geography", "hard", "Mount Kilimanjaro is in which country?", ["Kenya", "Tanzania", "Uganda", "Ethiopia"], 1),
    ("Geography", "hard", "Which is the largest hot desert?", ["Gobi", "Kalahari", "Sahara", "Arabian"], 2),
    ("History", "easy", "Who was the first Prime Minister of India?", ["Mahatma Gandhi", "Jawaharlal Nehru", "Sardar Patel", "B. R. Ambedkar"], 1),
    ("History", "easy", "In which year did India gain independence?", ["1942", "1945", "1947", "1950"], 2),
    ("History", "medium", "Who wrote the Indian national anthem?", ["Bankim Chandra Chatterjee", "Rabindranath Tagore", "Sarojini Naidu", "Muhammad Iqbal"], 1),
    ("History", "medium", "World War II ended in which year?", ["1943", "1944", "1945", "1946"], 2),
    ("History", "medium", "Who was the first Mughal emperor?", ["Akbar", "Babur", "Humayun", "Shah Jahan"], 1),
    ("History", "hard", "The Battle of Plassey was fought in which year?", ["1757", "1764", "1857", "1707"], 0),
    ("History", "hard", "Which civilization built Machu Picchu?", ["Aztec", "Maya", "Inca", "Olmec"], 2),
    ("General Knowledge", "easy", "How many days are in a leap year?", ["365", "366", "364", "367"], 1),
    ("General Knowledge", "easy", "What is the national animal of India?", ["Lion", "Elephant", "Tiger", "Peacock"], 2),
    ("General Knowledge", "medium", "Which is the largest mammal?", ["African elephant", "Blue whale", "Giraffe", "Hippopotamus"], 1),
    ("General Knowledge", "medium", "How many players per side in a cricket match?", ["9", "10", "11", "12"], 2),
    ("General Knowledge", "hard", "When were the first modern Olympic Games held?", ["1888", "1896", "1900", "1912"], 1),
    ("General Knowledge", "hard", "How many bones does an adult human have?", ["196", "206", "216", "226"], 1),
]

# ───────────────────────────── Database layer ─────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, username TEXT,
    language_code TEXT,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_active TEXT NOT NULL DEFAULT (datetime('now')),
    blocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy','medium','hard')),
    question TEXT NOT NULL, options TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK (correct BETWEEN 0 AND 3),
    explanation TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_q_filter ON questions (active, category_id, difficulty);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL DEFAULT 0, difficulty TEXT NOT NULL,
    question_ids TEXT NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0, current_qid INTEGER, message_id INTEGER,
    correct INTEGER NOT NULL DEFAULT 0, answered INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL DEFAULT (datetime('now')), finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_s_user ON sessions (user_id, status);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL, user_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL, difficulty TEXT NOT NULL,
    chosen INTEGER NOT NULL, is_correct INTEGER NOT NULL, points INTEGER NOT NULL DEFAULT 0,
    answered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_a_user ON answers (user_id);
"""


class DB:
    """Thin thread-safe SQLite wrapper (autocommit + explicit transactions)."""

    def __init__(self, path: str):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
        self.seed_if_empty()

    # -- primitives --
    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def run(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args)

    def all(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    # -- users --
    def upsert_user(self, uid, first, last, username, lang):
        self.run(
            """INSERT INTO users (user_id, first_name, last_name, username, language_code)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name,
                 last_name=excluded.last_name, username=excluded.username,
                 language_code=excluded.language_code, last_active=datetime('now'), blocked=0""",
            (uid, first, last, username, lang),
        )

    def get_user(self, uid):
        return self.one("SELECT * FROM users WHERE user_id=?", (uid,))

    def broadcast_targets(self):
        return [r["user_id"] for r in self.all("SELECT user_id FROM users WHERE blocked=0")]

    def mark_blocked(self, uid):
        self.run("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))

    # -- categories / questions --
    def category_id(self, name):
        self.run("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        return self.one("SELECT id FROM categories WHERE name=?", (name,))["id"]

    def categories_with_counts(self):
        return self.all(
            """SELECT c.id, c.name, COUNT(q.id) AS n FROM categories c
               LEFT JOIN questions q ON q.category_id=c.id AND q.active=1
               GROUP BY c.id ORDER BY c.name"""
        )

    def add_question(self, cat, diff, text, options, correct, explanation=""):
        cid = self.category_id(cat)
        cur = self.run(
            """INSERT INTO questions (category_id, difficulty, question, options, correct, explanation)
               VALUES (?,?,?,?,?,?)""",
            (cid, diff, text, json.dumps(options), correct, explanation),
        )
        return cur.lastrowid

    def get_question(self, qid):
        return self.one(
            """SELECT q.*, c.name AS category FROM questions q
               JOIN categories c ON c.id=q.category_id WHERE q.id=?""",
            (qid,),
        )

    def list_questions(self, offset, limit):
        return self.all(
            """SELECT q.id, q.question, q.difficulty, q.active, c.name AS category
               FROM questions q JOIN categories c ON c.id=q.category_id
               ORDER BY q.id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    def count_questions(self):
        return self.one("SELECT COUNT(*) AS n FROM questions")["n"]

    def toggle_question(self, qid):
        self.run("UPDATE questions SET active = 1 - active WHERE id=?", (qid,))

    def delete_question(self, qid):
        self.run("DELETE FROM questions WHERE id=?", (qid,))

    def seed_if_empty(self):
        if self.count_questions():
            return
        with self.tx():
            for cat, diff, text, opts, correct in SEED:
                self.add_question(cat, diff, text, opts, correct)
        log.info("Seeded %d starter questions", len(SEED))

    def pick_questions(self, uid, cat, diff, n):
        """Random questions, preferring ones this user has seen the least."""
        where, args = ["q.active=1"], []
        if cat:
            where.append("q.category_id=?")
            args.append(cat)
        if diff:
            where.append("q.difficulty=?")
            args.append(diff)
        sql = (
            "SELECT q.id FROM questions q WHERE " + " AND ".join(where)
            + " ORDER BY (SELECT COUNT(*) FROM answers a WHERE a.user_id=? AND a.question_id=q.id),"
            " RANDOM() LIMIT ?"
        )
        return [r["id"] for r in self.all(sql, (*args, uid, n))]

    # -- sessions --
    def create_session(self, uid, chat_id, cat, diff, qids):
        cur = self.run(
            """INSERT INTO sessions (user_id, chat_id, category_id, difficulty, question_ids)
               VALUES (?,?,?,?,?)""",
            (uid, chat_id, cat, diff, json.dumps(qids)),
        )
        return cur.lastrowid

    def get_session(self, sid):
        return self.one("SELECT * FROM sessions WHERE id=?", (sid,))

    def active_sessions(self, uid):
        return self.all("SELECT * FROM sessions WHERE user_id=? AND status='active'", (uid,))

    def set_current(self, sid, qid, idx):
        self.run(
            "UPDATE sessions SET current_qid=?, current_index=?, message_id=NULL WHERE id=?",
            (qid, idx, sid),
        )

    def set_message(self, sid, mid):
        self.run("UPDATE sessions SET message_id=? WHERE id=?", (mid, sid))

    def advance(self, sid):
        self.run("UPDATE sessions SET current_index=current_index+1 WHERE id=?", (sid,))

    def finish_session(self, sid, status):
        """Returns True only for the call that actually closed the session."""
        cur = self.run(
            """UPDATE sessions SET status=?, finished_at=datetime('now'), current_qid=NULL
               WHERE id=? AND status='active'""",
            (status, sid),
        )
        return cur.rowcount == 1

    def abandon_all_active(self):
        return self.run(
            "UPDATE sessions SET status='abandoned', finished_at=datetime('now') WHERE status='active'"
        ).rowcount

    def record_answer(self, sid, qid, chosen):
        """Atomically store an answer. Returns None for stale or duplicate answers."""
        with self.tx():
            s = self.one("SELECT * FROM sessions WHERE id=?", (sid,))
            if not s or s["status"] != "active" or s["current_qid"] != qid:
                return None
            q = self.one("SELECT * FROM questions WHERE id=?", (qid,))
            if q is None:  # question was deleted while the quiz was running
                self.run("UPDATE sessions SET current_qid=NULL WHERE id=?", (sid,))
                return {"skipped": True, "correct": False, "points": 0}
            correct = int(chosen == q["correct"])
            pts = POINTS[q["difficulty"]] if correct else 0
            try:
                self.run(
                    """INSERT INTO answers (session_id, user_id, question_id, category_id,
                       difficulty, chosen, is_correct, points) VALUES (?,?,?,?,?,?,?,?)""",
                    (sid, s["user_id"], qid, q["category_id"], q["difficulty"], chosen, correct, pts),
                )
            except sqlite3.IntegrityError:  # UNIQUE(session_id, question_id) → duplicate
                return None
            self.run(
                """UPDATE sessions SET answered=answered+1, correct=correct+?, points=points+?,
                   current_qid=NULL WHERE id=?""",
                (correct, pts, sid),
            )
            return {"skipped": False, "correct": bool(correct), "points": pts}

    # -- statistics --
    def user_stats(self, uid):
        tot = self.one(
            """SELECT COUNT(*) n, COALESCE(SUM(is_correct),0) c, COALESCE(SUM(points),0) p,
               COALESCE(SUM(chosen=-1),0) t FROM answers WHERE user_id=?""",
            (uid,),
        )
        quizzes = self.one(
            """SELECT COUNT(*) n, COALESCE(MAX(points),0) best FROM sessions
               WHERE user_id=? AND status!='active' AND answered>0""",
            (uid,),
        )
        by_diff = self.all(
            """SELECT difficulty, COUNT(*) n, SUM(is_correct) c FROM answers
               WHERE user_id=? GROUP BY difficulty""",
            (uid,),
        )
        by_cat = self.all(
            """SELECT c.name, COUNT(*) n, SUM(a.is_correct) c FROM answers a
               JOIN categories c ON c.id=a.category_id WHERE a.user_id=?
               GROUP BY a.category_id ORDER BY n DESC LIMIT 5""",
            (uid,),
        )
        return tot, quizzes, by_diff, by_cat

    def history(self, uid, limit=10):
        return self.all(
            """SELECT s.*, COALESCE(c.name,'All categories') AS cname FROM sessions s
               LEFT JOIN categories c ON c.id=s.category_id
               WHERE s.user_id=? AND s.status!='active' AND s.answered>0
               ORDER BY s.id DESC LIMIT ?""",
            (uid, limit),
        )

    def leaderboard(self, limit=10):
        return self.all(
            """SELECT u.user_id, u.first_name, u.username, SUM(a.points) pts, COUNT(*) n,
               SUM(a.is_correct) c FROM answers a JOIN users u ON u.user_id=a.user_id
               GROUP BY a.user_id ORDER BY pts DESC, c DESC, n ASC LIMIT ?""",
            (limit,),
        )

    def rank_of(self, uid):
        if not self.one("SELECT 1 FROM answers WHERE user_id=? LIMIT 1", (uid,)):
            return None
        r = self.one(
            """WITH t AS (SELECT user_id, SUM(points) p FROM answers GROUP BY user_id)
               SELECT (SELECT COUNT(*) FROM t WHERE p > (SELECT p FROM t WHERE user_id=?)) + 1 AS r""",
            (uid,),
        )
        return r["r"]

    def admin_stats(self):
        g = lambda sql: self.one(sql)[0]  # noqa: E731
        ans = self.one("SELECT COUNT(*) n, COALESCE(SUM(is_correct),0) c FROM answers")
        return {
            "users": g("SELECT COUNT(*) FROM users"),
            "new_today": g("SELECT COUNT(*) FROM users WHERE registered_at >= date('now')"),
            "active_24h": g("SELECT COUNT(*) FROM users WHERE last_active >= datetime('now','-1 day')"),
            "blocked": g("SELECT COUNT(*) FROM users WHERE blocked=1"),
            "quizzes": g("SELECT COUNT(*) FROM sessions WHERE status IN ('finished','stopped')"),
            "answers": ans["n"],
            "correct": ans["c"],
            "q_active": g("SELECT COUNT(*) FROM questions WHERE active=1"),
            "q_total": g("SELECT COUNT(*) FROM questions"),
            "cats": g("SELECT COUNT(*) FROM categories"),
            "top_cats": self.all(
                """SELECT c.name, COUNT(*) n FROM answers a JOIN categories c ON c.id=a.category_id
                   GROUP BY c.id ORDER BY n DESC LIMIT 3"""
            ),
            "recent": self.all(
                "SELECT user_id, first_name, username, registered_at FROM users ORDER BY registered_at DESC, user_id DESC LIMIT 5"
            ),
        }


db = DB(DB_PATH)

# ───────────────────────────── Helpers ─────────────────────────────


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def pct(c, n) -> str:
    return f"{(c or 0) * 100 / n:.0f}%" if n else "0%"


def trunc(s, n) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_date(s) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return s or "—"


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def B(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows])


def register(user) -> None:
    db.upsert_user(user.id, user.first_name, user.last_name, user.username, user.language_code)


def main_menu(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [B("▶️ Start Quiz", "m:start"), B("📚 Categories", "m:cats")],
        [B("🏆 Leaderboard", "m:lb"), B("👤 My Profile", "m:prof")],
        [B("📊 My Statistics", "m:stats"), B("ℹ️ About Bot", "m:about")],
        [B("❓ Help", "m:help")],
    ]
    if is_admin(uid):
        rows.append([B("⚙️ Admin Panel", "a:panel")])
    return InlineKeyboardMarkup(rows)


BACK_MENU = kb([B("🏠 Main Menu", "m:main")])


async def safe_delete(msg) -> None:
    try:
        await msg.delete()
    except TelegramError:
        pass


async def safe_edit(q, text: str, markup=None) -> None:
    """Edit the message behind a callback; fall back to a fresh message if needed."""
    msg = q.message
    try:
        if getattr(msg, "photo", None):  # photo messages can't be turned into text
            await safe_delete(msg)
            await msg.chat.send_message(text, parse_mode=HTML, reply_markup=markup)
        else:
            await q.edit_message_text(text, parse_mode=HTML, reply_markup=markup)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        log.warning("edit failed (%s); sending new message", e)
        await msg.chat.send_message(text, parse_mode=HTML, reply_markup=markup)


async def show(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await safe_edit(update.callback_query, text, markup)
    else:
        await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=markup)


def profile_text(user, row) -> str:
    return (
        "👤 <b>Your Profile</b>\n\n"
        f"<b>First name:</b> {esc(user.first_name) or '—'}\n"
        f"<b>Last name:</b> {esc(user.last_name) or '—'}\n"
        f"<b>Username:</b> {'@' + esc(user.username) if user.username else '—'}\n"
        f"<b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"<b>Language:</b> {esc(user.language_code) or '—'}\n"
        f"<b>Registered:</b> {fmt_date(row['registered_at'])}"
    )


async def send_profile(bot, chat_id: int, user, header: str = "") -> None:
    row = db.get_user(user.id)
    text = header + profile_text(user, row)
    markup = main_menu(user.id)
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            await bot.send_photo(
                chat_id, photos.photos[0][-1].file_id, caption=text, parse_mode=HTML, reply_markup=markup
            )
            return
    except TelegramError as e:
        log.info("Profile photo unavailable for %s: %s", user.id, e)
    await bot.send_message(chat_id, text, parse_mode=HTML, reply_markup=markup)


# ───────────────────────────── Screens ─────────────────────────────


async def screen_main(update, context):
    await show(update, "🏠 <b>Main Menu</b>\nChoose an option below:", main_menu(update.effective_user.id))


async def screen_start(update, context):
    await show(
        update,
        "▶️ <b>Start Quiz</b>\nPick how you want to play:",
        kb(
            [B("🎲 Random Mix", "go:0:x")],
            [B("🟢 Easy", "go:0:e"), B("🟡 Medium", "go:0:m"), B("🔴 Hard", "go:0:h")],
            [B("📚 Pick a Category", "m:cats")],
            [B("🏠 Main Menu", "m:main")],
        ),
    )


async def screen_cats(update, context):
    cats = [c for c in db.categories_with_counts() if c["n"] > 0]
    if not cats:
        await show(update, "📚 No categories with questions yet.", BACK_MENU)
        return
    rows = [
        [B(f"{c['name']} ({c['n']})", f"cc:{c['id']}") for c in cats[i : i + 2]]
        for i in range(0, len(cats), 2)
    ]
    rows.append([B("🏠 Main Menu", "m:main")])
    await show(update, "📚 <b>Categories</b>\nChoose a category:", InlineKeyboardMarkup(rows))


async def screen_cat_diff(update, context, cat_id: int):
    cat = db.one("SELECT * FROM categories WHERE id=?", (cat_id,))
    if not cat:
        await show(update, "⚠️ That category no longer exists.", kb([B("📚 Categories", "m:cats")]))
        return
    counts = {
        r["difficulty"]: r["n"]
        for r in db.all(
            "SELECT difficulty, COUNT(*) n FROM questions WHERE active=1 AND category_id=? GROUP BY difficulty",
            (cat_id,),
        )
    }
    row = [B(f"{DEMOJI[d]} {d.title()} ({n})", f"go:{cat_id}:{DCODE[d]}") for d, n in counts.items()]
    await show(
        update,
        f"📚 <b>{esc(cat['name'])}</b>\nChoose a difficulty:",
        kb(row, [B("🎲 Mixed", f"go:{cat_id}:x")], [B("⬅️ Categories", "m:cats"), B("🏠 Menu", "m:main")]),
    )


async def screen_leaderboard(update, context):
    uid = update.effective_user.id
    rows = db.leaderboard(10)
    if not rows:
        await show(update, "🏆 <b>Leaderboard</b>\n\nNo scores yet — be the first to play!", BACK_MENU)
        return
    medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    lines = ["🏆 <b>Top 10 Leaderboard</b>\n"]
    for medal, r in zip(medals, rows):
        name = esc(trunc(r["first_name"] or r["username"] or r["user_id"], 18))
        you = " 👈" if r["user_id"] == uid else ""
        lines.append(f"{medal} <b>{name}</b> — {r['pts']} pts · {pct(r['c'], r['n'])} ({r['n']} answers){you}")
    rank = db.rank_of(uid)
    lines.append(f"\n<b>Your rank:</b> {'#' + str(rank) if rank else 'unranked — play a quiz!'}")
    await show(update, "\n".join(lines), kb([B("▶️ Play", "m:start"), B("🏠 Menu", "m:main")]))


async def screen_stats(update, context):
    uid = update.effective_user.id
    tot, quizzes, by_diff, by_cat = db.user_stats(uid)
    if not tot["n"]:
        await show(update, "📊 <b>My Statistics</b>\n\nYou haven't answered anything yet.", kb([B("▶️ Start Quiz", "m:start")], [B("🏠 Main Menu", "m:main")]))
        return
    rank = db.rank_of(uid)
    lines = [
        "📊 <b>My Statistics</b>\n",
        f"🎮 Quizzes played: <b>{quizzes['n']}</b>",
        f"❓ Questions answered: <b>{tot['n']}</b>",
        f"✅ Correct: <b>{tot['c']}</b>   ⏰ Timeouts: <b>{tot['t']}</b>",
        f"🎯 Accuracy: <b>{pct(tot['c'], tot['n'])}</b>",
        f"⭐ Total points: <b>{tot['p']}</b>   🏅 Best quiz: <b>{quizzes['best']}</b> pts",
        f"🏆 Rank: <b>#{rank}</b>",
    ]
    if by_diff:
        lines.append("\n<b>By difficulty</b>")
        for r in sorted(by_diff, key=lambda r: list(POINTS).index(r["difficulty"])):
            lines.append(f"{DEMOJI[r['difficulty']]} {r['difficulty'].title()}: {pct(r['c'], r['n'])} ({r['n']})")
    if by_cat:
        lines.append("\n<b>Top categories</b>")
        for r in by_cat:
            lines.append(f"• {esc(r['name'])}: {pct(r['c'], r['n'])} ({r['n']})")
    await show(update, "\n".join(lines), kb([B("📜 Quiz History", "m:hist")], [B("🏠 Main Menu", "m:main")]))


async def screen_history(update, context):
    rows = db.history(update.effective_user.id, 10)
    if not rows:
        await show(update, "📜 <b>Quiz History</b>\n\nNo completed quizzes yet.", BACK_MENU)
        return
    lines = ["📜 <b>Your last quizzes</b>\n"]
    for r in rows:
        when = (r["finished_at"] or r["started_at"])[:16]
        lines.append(
            f"{when} · {DEMOJI.get(r['difficulty'], '🎲')} {esc(r['difficulty'].title())} · {esc(trunc(r['cname'], 16))}\n"
            f"   ✅ {r['correct']}/{r['answered']} ({pct(r['correct'], r['answered'])}) · ⭐ {r['points']} pts"
        )
    await show(update, "\n".join(lines), kb([B("📊 Statistics", "m:stats"), B("🏠 Menu", "m:main")]))


async def screen_about(update, context):
    n = db.one("SELECT COUNT(*) FROM questions WHERE active=1")[0]
    c = db.one("SELECT COUNT(DISTINCT category_id) FROM questions WHERE active=1")[0]
    await show(
        update,
        "ℹ️ <b>About Quiz Bot</b>\n\n"
        "A multiple-choice quiz bot with categories, difficulty levels, timers, "
        "a global leaderboard and personal statistics.\n\n"
        f"📚 Questions: <b>{n}</b> in <b>{c}</b> categories\n"
        f"🔢 Quiz length: <b>{QUIZ_LENGTH}</b> questions\n"
        f"⏱ Time per question: <b>{QUESTION_TIME}s</b>\n"
        f"⭐ Points: 🟢 {POINTS['easy']} · 🟡 {POINTS['medium']} · 🔴 {POINTS['hard']}",
        BACK_MENU,
    )


async def screen_help(update, context):
    await show(
        update,
        "❓ <b>How to play</b>\n\n"
        "1️⃣ Tap <b>Start Quiz</b> or pick a <b>Category</b>.\n"
        "2️⃣ Choose a difficulty.\n"
        f"3️⃣ Answer each question within <b>{QUESTION_TIME} seconds</b> using the A/B/C/D buttons.\n"
        "4️⃣ Each question can be answered only once; unanswered ones count as wrong.\n"
        "5️⃣ Earn points for every correct answer and climb the leaderboard.\n\n"
        "<b>Commands</b>\n/start – profile &amp; menu\n/menu – main menu\n/help – this message\n"
        "/cancel – cancel an admin action",
        BACK_MENU,
    )


# ───────────────────────────── Quiz engine ─────────────────────────────


def cancel_timer(context, sid: int) -> None:
    for job in context.job_queue.get_jobs_by_name(f"qt:{sid}"):
        job.schedule_removal()


def q_header(s, total: int, q) -> str:
    return (
        f"❓ <b>Question {s['current_index'] + 1}/{total}</b> · "
        f"{DEMOJI[q['difficulty']]} {q['difficulty'].title()} · {esc(q['category'])}\n\n"
        f"<b>{esc(q['question'])}</b>"
    )


async def abandon_active(context, uid: int) -> None:
    for s in db.active_sessions(uid):
        cancel_timer(context, s["id"])
        db.finish_session(s["id"], "abandoned")
        if s["message_id"]:
            try:
                await context.bot.edit_message_reply_markup(s["chat_id"], s["message_id"], reply_markup=None)
            except TelegramError:
                pass


async def send_question(context, sid: int) -> None:
    s = db.get_session(sid)
    if not s or s["status"] != "active":
        return
    ids = json.loads(s["question_ids"])
    idx, q = s["current_index"], None
    while idx < len(ids):  # skip questions that were disabled/deleted meanwhile
        q = db.get_question(ids[idx])
        if q and q["active"]:
            break
        q, idx = None, idx + 1
    if q is None:
        await finish_quiz(context, sid, "finished")
        return

    db.set_current(sid, q["id"], idx)
    s = db.get_session(sid)
    opts = json.loads(q["options"])
    order = [0, 1, 2, 3]
    random.shuffle(order)  # shuffle display; callbacks carry the ORIGINAL option index
    body = "\n".join(f"{LETTERS[i]}) {esc(opts[o])}" for i, o in enumerate(order))
    text = f"{q_header(s, len(ids), q)}\n\n{body}\n\n⏱ {QUESTION_TIME}s · ⭐ {s['points']} pts"
    markup = kb(
        [B(LETTERS[i], f"ans:{sid}:{q['id']}:{o}") for i, o in enumerate(order)],
        [B("🛑 Stop Quiz", f"quit:{sid}")],
    )
    msg = await context.bot.send_message(s["chat_id"], text, parse_mode=HTML, reply_markup=markup)
    db.set_message(sid, msg.message_id)
    context.job_queue.run_once(
        question_timeout, QUESTION_TIME, data={"sid": sid, "qid": q["id"]}, name=f"qt:{sid}"
    )


async def question_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.job.data
    await resolve_question(context, d["sid"], d["qid"], -1)


async def resolve_question(context, sid: int, qid: int, chosen: int, query=None):
    """Record an answer (or timeout), show the result, then move to the next question."""
    res = db.record_answer(sid, qid, chosen)
    if query is not None:  # answer the callback immediately to stop the spinner
        if res is None:
            await query.answer("⚠️ Already answered or expired.")
        else:
            await query.answer("✅ Correct!" if res["correct"] else "❌ Wrong!")
    if res is None:
        return None

    cancel_timer(context, sid)
    s = db.get_session(sid)
    q = db.get_question(qid)
    total = len(json.loads(s["question_ids"]))
    if res["skipped"] or q is None:
        result = "⚠️ This question was removed by an admin. Skipping."
        head = f"❓ <b>Question {s['current_index'] + 1}/{total}</b>"
    else:
        opts = json.loads(q["options"])
        if chosen == -1:
            verdict = "⏰ <b>Time's up!</b>"
        elif res["correct"]:
            verdict = f"✅ <b>Correct!</b> +{res['points']} pts"
        else:
            verdict = f"❌ <b>Wrong.</b> You chose: {esc(opts[chosen])}"
        result = f"{verdict}\n\n<b>Correct answer:</b> {esc(opts[q['correct']])}"
        if q["explanation"]:
            result += f"\n💡 {esc(q['explanation'])}"
        head = q_header(s, total, q)
    if s["message_id"]:
        try:
            await context.bot.edit_message_text(
                f"{head}\n\n{result}", chat_id=s["chat_id"], message_id=s["message_id"], parse_mode=HTML
            )
        except TelegramError as e:
            log.info("Could not edit question message: %s", e)

    db.advance(sid)
    await send_question(context, sid)
    return res


async def finish_quiz(context, sid: int, status: str = "finished") -> None:
    cancel_timer(context, sid)
    if not db.finish_session(sid, status):
        return
    s = db.get_session(sid)
    n, c = s["answered"], s["correct"]
    acc = c * 100 / n if n else 0
    verdict = (
        "🌟 Outstanding!" if acc >= 90 else "👏 Great job!" if acc >= 70
        else "👍 Good effort!" if acc >= 50 else "📖 Keep practising!"
    )
    title = "Quiz finished!" if status == "finished" else "Quiz stopped."
    text = (
        f"🏁 <b>{title}</b>\n\n✅ Correct: <b>{c}/{n}</b>\n🎯 Accuracy: <b>{acc:.0f}%</b>\n"
        f"⭐ Points earned: <b>{s['points']}</b>\n\n{verdict}"
    )
    await context.bot.send_message(
        s["chat_id"],
        text,
        parse_mode=HTML,
        reply_markup=kb(
            [B("🔁 Play Again", f"go:{s['category_id']}:{DCODE[s['difficulty']]}"), B("🏆 Leaderboard", "m:lb")],
            [B("📊 My Stats", "m:stats"), B("🏠 Main Menu", "m:main")],
        ),
    )


async def start_quiz(update, context, cat: int, dcode: str) -> None:
    q = update.callback_query
    user = q.from_user
    diff = DNAME.get(dcode)
    if diff is None:
        await q.answer("Unknown difficulty.", show_alert=True)
        return
    ids = db.pick_questions(user.id, cat, None if diff == "mixed" else diff, QUIZ_LENGTH)
    if not ids:
        await q.answer("No questions available for this selection yet.", show_alert=True)
        return
    await abandon_active(context, user.id)
    sid = db.create_session(user.id, q.message.chat.id, cat, diff, ids)
    await q.answer("Quiz started! 🚀")
    row = db.one("SELECT name FROM categories WHERE id=?", (cat,)) if cat else None
    await safe_edit(
        q,
        f"🎯 <b>Quiz started!</b>\n{DEMOJI[diff]} {diff.title()} · {esc(row['name']) if row else 'All categories'}\n"
        f"{len(ids)} questions · {QUESTION_TIME}s each",
    )
    await send_question(context, sid)


async def cb_answer(update, context, parts) -> None:
    q = update.callback_query
    sid, qid, choice = int(parts[1]), int(parts[2]), int(parts[3])
    s = db.get_session(sid)
    if not s or s["user_id"] != q.from_user.id:
        await q.answer("This isn't your quiz.", show_alert=True)
        return
    if choice not in range(4):
        await q.answer("Invalid option.", show_alert=True)
        return
    await resolve_question(context, sid, qid, choice, query=q)


async def cb_quit(update, context, parts) -> None:
    q = update.callback_query
    sid = int(parts[1])
    s = db.get_session(sid)
    if not s or s["user_id"] != q.from_user.id:
        await q.answer("This isn't your quiz.", show_alert=True)
        return
    if s["status"] != "active":
        await q.answer("This quiz is already over.")
        return
    await q.answer("Quiz stopped.")
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await finish_quiz(context, sid, "stopped")


# ───────────────────────────── Admin panel ─────────────────────────────


def parse_question(text: str):
    parts = [p.strip() for p in text.split("|")]
    if len(parts) not in (8, 9):
        raise ValueError("Expected 8 fields (9 with explanation) separated by |")
    cat, diff, ques, a, b, c, d, ans = parts[:8]
    expl = parts[8] if len(parts) == 9 else ""
    diff, ans = diff.lower(), ans.upper()
    if diff not in POINTS:
        raise ValueError("Difficulty must be easy, medium or hard")
    if len(ans) != 1 or ans not in LETTERS:
        raise ValueError("Correct answer must be A, B, C or D")
    if not cat or len(cat) > 30:
        raise ValueError("Category is required (max 30 characters)")
    if not ques or len(ques) > 300:
        raise ValueError("Question is required (max 300 characters)")
    opts = [a, b, c, d]
    if any(not o or len(o) > 100 for o in opts):
        raise ValueError("Each option is required (max 100 characters)")
    if len({o.lower() for o in opts}) < 4:
        raise ValueError("Options must be different from each other")
    if len(expl) > 300:
        raise ValueError("Explanation is max 300 characters")
    return cat, diff, ques, opts, LETTERS.index(ans), expl


ADD_Q_HELP = (
    "➕ <b>Add question</b>\n\nSend ONE message in this format:\n\n"
    "<code>Category | difficulty | Question | Option A | Option B | Option C | Option D | Correct letter | Explanation (optional)</code>\n\n"
    "Example:\n<code>Science | easy | Which planet is closest to the Sun? | Venus | Mercury | Earth | Mars | B | Mercury orbits closest.</code>\n\n"
    "Send /cancel to abort."
)


async def screen_admin_panel(update, context):
    await show(
        update,
        "⚙️ <b>Admin Panel</b>",
        kb(
            [B("📈 User Statistics", "a:stats")],
            [B("❓ Manage Questions", "a:ql:0")],
            [B("📢 Broadcast", "a:bc")],
            [B("🏠 Main Menu", "m:main")],
        ),
    )


async def admin_stats(update, context):
    s = db.admin_stats()
    lines = [
        "📈 <b>Bot Statistics</b>\n",
        f"👥 Users: <b>{s['users']}</b> (new today: {s['new_today']}, active 24h: {s['active_24h']}, blocked: {s['blocked']})",
        f"🎮 Quizzes completed: <b>{s['quizzes']}</b>",
        f"❓ Answers: <b>{s['answers']}</b> · accuracy {pct(s['correct'], s['answers'])}",
        f"📚 Questions: <b>{s['q_active']}</b> active / {s['q_total']} total in {s['cats']} categories",
    ]
    if s["top_cats"]:
        lines.append("\n<b>Most played categories</b>")
        lines += [f"• {esc(r['name'])} ({r['n']} answers)" for r in s["top_cats"]]
    if s["recent"]:
        lines.append("\n<b>Newest users</b>")
        for r in s["recent"]:
            who = esc(r["first_name"] or "—") + (f" (@{esc(r['username'])})" if r["username"] else "")
            lines.append(f"• {who} — <code>{r['user_id']}</code> · {r['registered_at'][:10]}")
    await show(update, "\n".join(lines), kb([B("🔄 Refresh", "a:stats")], [B("⬅️ Admin Panel", "a:panel")]))


async def admin_question_list(update, context, page: int):
    total = db.count_questions()
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    rows = db.list_questions(page * PAGE_SIZE, PAGE_SIZE)
    buttons = [
        [B(f"{'✅' if r['active'] else '🚫'} #{r['id']} {r['difficulty'][0].upper()} · {trunc(r['question'], 30)}", f"a:qv:{r['id']}")]
        for r in rows
    ]
    nav = []
    if page > 0:
        nav.append(B("⬅️ Prev", f"a:ql:{page - 1}"))
    if page < pages - 1:
        nav.append(B("➡️ Next", f"a:ql:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([B("➕ Add Question", "a:qa")])
    buttons.append([B("⬅️ Admin Panel", "a:panel")])
    await show(
        update,
        f"❓ <b>Questions</b> — {total} total · page {page + 1}/{pages}\n✅ active · 🚫 disabled · E/M/H = difficulty",
        InlineKeyboardMarkup(buttons),
    )


async def admin_question_view(update, context, qid: int):
    q = db.get_question(qid)
    if not q:
        await show(update, "⚠️ Question not found.", kb([B("⬅️ List", "a:ql:0")]))
        return
    opts = json.loads(q["options"])
    lines = [
        f"❓ <b>Question #{q['id']}</b> — {'✅ active' if q['active'] else '🚫 disabled'}",
        f"{DEMOJI[q['difficulty']]} {q['difficulty'].title()} · {esc(q['category'])}\n",
        f"<b>{esc(q['question'])}</b>\n",
    ]
    lines += [f"{'✅' if i == q['correct'] else '▫️'} {LETTERS[i]}) {esc(o)}" for i, o in enumerate(opts)]
    if q["explanation"]:
        lines.append(f"\n💡 {esc(q['explanation'])}")
    await show(
        update,
        "\n".join(lines),
        kb(
            [B("🚫 Disable" if q["active"] else "✅ Enable", f"a:qt:{qid}"), B("🗑 Delete", f"a:qd:{qid}")],
            [B("⬅️ List", "a:ql:0")],
        ),
    )


async def admin_router(update, context, a: list) -> None:
    cmd = a[0]
    if cmd == "panel":
        context.user_data.pop("await", None)
        await screen_admin_panel(update, context)
    elif cmd == "stats":
        await admin_stats(update, context)
    elif cmd == "ql":
        await admin_question_list(update, context, int(a[1]))
    elif cmd == "qv":
        await admin_question_view(update, context, int(a[1]))
    elif cmd == "qt":
        db.toggle_question(int(a[1]))
        await admin_question_view(update, context, int(a[1]))
    elif cmd == "qd":
        await show(
            update,
            f"🗑 Delete question #{a[1]} permanently?",
            kb([B("Yes, delete", f"a:qdy:{a[1]}"), B("Cancel", f"a:qv:{a[1]}")]),
        )
    elif cmd == "qdy":
        db.delete_question(int(a[1]))
        await admin_question_list(update, context, 0)
    elif cmd == "qa":
        context.user_data["await"] = "addq"
        await show(update, ADD_Q_HELP, kb([B("❌ Cancel", "a:ql:0")]))
    elif cmd == "bc":
        context.user_data["await"] = "bc"
        await show(
            update,
            "📢 <b>Broadcast</b>\n\nSend the message you want to deliver to all users "
            "(text, photo, etc.). I'll show a preview first.\n\nSend /cancel to abort.",
            kb([B("❌ Cancel", "a:panel")]),
        )
    elif cmd == "bcy":
        pending = context.user_data.pop("bc_msg", None)
        if not pending:
            await show(update, "⚠️ Nothing to send.", kb([B("⬅️ Admin Panel", "a:panel")]))
            return
        await show(update, "📢 Broadcast started… I'll report when it's done.", kb([B("⬅️ Admin Panel", "a:panel")]))
        context.application.create_task(run_broadcast(context.bot, update.effective_chat.id, *pending))
    elif cmd == "bcn":
        context.user_data.pop("bc_msg", None)
        await screen_admin_panel(update, context)
    else:
        await update.callback_query.answer("Unknown admin action.")


async def run_broadcast(bot, admin_chat: int, from_chat: int, message_id: int) -> None:
    ok = failed = 0
    for uid in db.broadcast_targets():
        try:
            await bot.copy_message(uid, from_chat, message_id)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(uid, from_chat, message_id)
                ok += 1
            except TelegramError:
                failed += 1
        except Forbidden:
            db.mark_blocked(uid)
            failed += 1
        except TelegramError as e:
            log.info("Broadcast to %s failed: %s", uid, e)
            failed += 1
        await asyncio.sleep(0.06)  # stay well below Telegram's ~30 msg/s limit
    await bot.send_message(admin_chat, f"📢 Broadcast finished.\n✅ Delivered: {ok}\n❌ Failed: {failed}")


# ───────────────────────────── Telegram handlers ─────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register(user)
    context.user_data.clear()
    await send_profile(
        context.bot, update.effective_chat.id, user,
        header="🎓 <b>Welcome to Quiz Bot!</b> Test your knowledge and climb the leaderboard.\n\n",
    )


async def cmd_menu(update, context):
    register(update.effective_user)
    await screen_main(update, context)


async def cmd_help(update, context):
    register(update.effective_user)
    await screen_help(update, context)


async def cmd_admin(update, context):
    register(update.effective_user)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return
    await screen_admin_panel(update, context)


async def cmd_cancel(update, context):
    context.user_data.pop("await", None)
    context.user_data.pop("bc_msg", None)
    await update.message.reply_text("Cancelled.", reply_markup=main_menu(update.effective_user.id))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    register(q.from_user)
    parts = (q.data or "").split(":")
    action = parts[0]

    if action == "ans":
        await cb_answer(update, context, parts)
    elif action == "quit":
        await cb_quit(update, context, parts)
    elif action == "go":
        await start_quiz(update, context, int(parts[1]), parts[2])
    elif action == "m":
        await q.answer()
        if parts[1] == "prof":
            await safe_delete(q.message)
            await send_profile(context.bot, q.message.chat.id, q.from_user)
            return
        screens = {
            "main": screen_main, "start": screen_start, "cats": screen_cats, "lb": screen_leaderboard,
            "stats": screen_stats, "hist": screen_history, "about": screen_about, "help": screen_help,
        }
        await screens.get(parts[1], screen_main)(update, context)
    elif action == "cc":
        await q.answer()
        await screen_cat_diff(update, context, int(parts[1]))
    elif action == "a":
        if not is_admin(q.from_user.id):
            await q.answer("⛔ Admins only.", show_alert=True)
            return
        await q.answer()
        await admin_router(update, context, parts[1:])
    else:
        await q.answer("Unknown action.")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None:
        return
    user = update.effective_user
    register(user)
    state = context.user_data.get("await")
    if not state or not is_admin(user.id):
        await msg.reply_text("Use the menu below 👇", reply_markup=main_menu(user.id))
        return

    if state == "addq":
        try:
            cat, diff, text, opts, correct, expl = parse_question(msg.text or "")
        except ValueError as e:
            await msg.reply_text(f"❌ {e}\n\nFix it and send again, or /cancel.")
            return
        qid = db.add_question(cat, diff, text, opts, correct, expl)
        context.user_data.pop("await", None)
        await msg.reply_text(
            f"✅ Question #{qid} added to <b>{esc(cat)}</b> ({diff}).",
            parse_mode=HTML,
            reply_markup=kb([B("➕ Add Another", "a:qa"), B("📋 List", "a:ql:0")], [B("⬅️ Admin Panel", "a:panel")]),
        )
    elif state == "bc":
        context.user_data["bc_msg"] = (msg.chat_id, msg.message_id)
        context.user_data.pop("await", None)
        count = len(db.broadcast_targets())
        await msg.reply_text("👆 Preview of your broadcast:")
        await context.bot.copy_message(msg.chat_id, msg.chat_id, msg.message_id)
        await msg.reply_text(
            f"Send this to <b>{count}</b> users?",
            parse_mode=HTML,
            reply_markup=kb([B("✅ Send now", "a:bcy"), B("❌ Cancel", "a:bcn")]),
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception", exc_info=context.error)
    if not isinstance(update, Update):
        return
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Something went wrong. Please try again.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("⚠️ Something went wrong. Please try again.")
    except TelegramError:
        pass


async def post_init(app: Application) -> None:
    stale = db.abandon_all_active()  # in-memory timers don't survive a restart
    if stale:
        log.info("Closed %d quiz sessions left over from the previous run", stale)
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Profile & main menu"),
            BotCommand("menu", "Open main menu"),
            BotCommand("help", "How to play"),
            BotCommand("cancel", "Cancel current action"),
        ]
    )


def main() -> None:
    app = Application.builder().token(TOKEN).concurrent_updates(True).post_init(post_init).build()
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler("menu", cmd_menu, filters=private))
    app.add_handler(CommandHandler("help", cmd_help, filters=private))
    app.add_handler(CommandHandler("admin", cmd_admin, filters=private))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=private))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(private & filters.ALL & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)

    if BASE_URL:
        log.info("Starting webhook on port %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=f"{BASE_URL}/{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=False,  # keep the update that woke a sleeping Render service
        )
    else:
        log.info("No WEBHOOK_URL/RENDER_EXTERNAL_URL set → polling mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
