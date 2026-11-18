# Telegram Quiz Bot

Python + python-telegram-bot 21 + SQLite. Runs on Render (webhook) or locally (polling).

## Features
- `/start`: first name, last name, username, Telegram ID, language, profile photo (if any), registration date
- Inline menu: Start Quiz · Categories · Leaderboard · My Profile · My Statistics · About Bot · Help
- 4-option MCQs, per-question timer, easy/medium/hard/mixed, categories, points (10/15/20)
- Duplicate-answer protection (DB `UNIQUE(session_id, question_id)` + atomic transaction)
- Quiz history, accuracy, per-difficulty/category stats, Top 10 leaderboard + your rank
- Admin panel: user statistics, add/enable/disable/delete questions, broadcast (any message type, with preview)
- 35 starter questions are seeded automatically on first run

## Environment variables
| Name | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | Token from @BotFather |
| `ADMIN_ID` | yes | Your numeric Telegram ID (comma-separate for several admins) |
| `QUIZ_LENGTH` | no | Questions per quiz (default 5) |
| `QUESTION_TIME` | no | Seconds per question (default 20) |
| `DB_PATH` | no | SQLite file path (default `quiz_bot.db`) |
| `WEBHOOK_URL` | no | Public URL; Render's `RENDER_EXTERNAL_URL` is used automatically |

No secrets are stored in code; `.env` is git-ignored.

## Run locally
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # fill BOT_TOKEN and ADMIN_ID
python main.py           # polling mode
```

## Deploy on Render
1. Push this folder to GitHub (without `.env`).
2. Render → **New → Blueprint** → select the repo (`render.yaml` is picked up).
3. Set `BOT_TOKEN` and `ADMIN_ID` in the dashboard, deploy.
4. Logs should show `Starting webhook on port ...`. Send `/start` to your bot.

### Important: data persistence
Render's **free** plan has an ephemeral disk, so the SQLite file (users, scores, added questions) is
**reset on every restart/redeploy** and after sleep-restarts. To keep data: use a paid plan, attach a disk
(see the commented block in `render.yaml`) and set `DB_PATH=/var/data/quiz_bot.db`.
The free plan also sleeps after ~15 min idle; the next message wakes it (30-60 s delay).

## Admin usage
Open **⚙️ Admin Panel** from the menu (or `/admin`).
Add a question by sending:
```
Category | difficulty | Question | Option A | Option B | Option C | Option D | Correct letter | Explanation (optional)
```
Example: `Science | easy | Which planet is closest to the Sun? | Venus | Mercury | Earth | Mars | B`

## Notes
- Quiz timers live in memory; if the bot restarts, running quizzes are closed automatically.
- Find your numeric ID with @userinfobot.
