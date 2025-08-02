from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3, os
import traceback
from utils import run_agent_sync

app = Flask(__name__)
app.secret_key = 'supersecretkey'
DB_NAME = 'users.db'

@app.before_request
def make_session_non_permanent():
    session.permanent = False


# INIT DB 
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            goal TEXT,
            youtube_url TEXT,
            drive_url TEXT,
            notion_url TEXT,
            result TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_config (
            user_id INTEGER PRIMARY KEY,
            google_api_key TEXT,
            youtube_url TEXT,
            drive_url TEXT,
            notion_url TEXT
        )''')

#  ROUTES 
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                flash("Registered successfully. Please login.", "success")
                return redirect(url_for('login'))
        except:
            flash("Username already exists.", "danger")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with sqlite3.connect(DB_NAME) as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username=? AND password=?", 
                (username, password)
            ).fetchone()

            if user:
                session['user_id'] = user[0]
                session['username'] = user[1]

                # 🔍 Check if config exists for this user
                config = conn.execute(
                    "SELECT * FROM user_config WHERE user_id=?", 
                    (user[0],)
                ).fetchone()

                if not config:
                    flash("Please complete your configuration to continue.", "info")
                    return redirect(url_for('config'))  # Or 'manageconfig' if that's the route

                return redirect(url_for('dashboard'))
            else:
                flash("Invalid credentials", "danger")

    return render_template('login.html')


@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    config = None
    with sqlite3.connect(DB_NAME) as conn:
        config = conn.execute("SELECT * FROM user_config WHERE user_id=?", (session['user_id'],)).fetchone()

    return render_template('dashboard.html', username=session['username'], config=config)

@app.route('/generate', methods=['POST'])
def generate():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    goal = request.form['goal']
    session['goal'] = goal

    try:
        with sqlite3.connect(DB_NAME) as conn:
            config = conn.execute("SELECT * FROM user_config WHERE user_id=?", (session['user_id'],)).fetchone()

        if not config:
            flash("Configuration not found. Please set it up first.", "danger")
            return redirect(url_for('config'))

        # Unpack config safely
        google_api_key = config[1]
        youtube_url = config[2]
        drive_url = config[3] if config[3] else None
        notion_url = config[4] if config[4] else None

        result = run_agent_sync(
            google_api_key=google_api_key,
            youtube_pipedream_url=youtube_url,
            drive_pipedream_url=drive_url,
            notion_pipedream_url=notion_url,
            user_goal=goal
        )

        if not result or 'messages' not in result:
            raise Exception("Invalid response from AI engine. Check your API key or URLs.")

        response = "\n".join([msg.content for msg in result['messages']])

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("""
                INSERT INTO user_goals (user_id, goal, youtube_url, drive_url, notion_url, result)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session['user_id'], goal, youtube_url, drive_url, notion_url, response))

        return render_template('generate.html', username=session['username'], result=response)

    except Exception as e:
        return render_template(
            'generate.html',
            username=session['username'],
            error=str(e),
            debug=traceback.format_exc()
        )

    

    if 'user_id' not in session:
        return redirect(url_for('login'))

    goal = request.form['goal']
    session['goal'] = goal

    with sqlite3.connect(DB_NAME) as conn:
        config = conn.execute("SELECT * FROM user_config WHERE user_id=?", (session['user_id'],)).fetchone()

    if not config:
        flash("Configuration not found. Please set it up first.", "danger")
        return redirect(url_for('config'))

    result = run_agent_sync(
        google_api_key=config[1],
        youtube_pipedream_url=config[2],
        drive_pipedream_url=config[3],
        notion_pipedream_url=config[4],
        user_goal=goal
    )
    response = "\n".join([msg.content for msg in result['messages']])

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO user_goals (user_id, goal, youtube_url, drive_url, notion_url, result)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (session['user_id'], goal, config[2], config[3], config[4], response))

    return render_template('generate.html', username=session['username'], result=response)

@app.route('/config', methods=['GET', 'POST'])
def config():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        google_api_key = request.form['google_api_key'].strip()
        youtube_url = request.form['youtube_url'].strip()

        drive_url = request.form.get('drive_url', '').strip() if 'drive_enabled' in request.form else ''
        notion_url = request.form.get('notion_url', '').strip() if 'notion_enabled' in request.form else ''

        def fix_url(url):
            return url if url.startswith('http') else f'https://{url}'

        youtube_url = fix_url(youtube_url)
        drive_url = fix_url(drive_url) if drive_url else None
        notion_url = fix_url(notion_url) if notion_url else None

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_config (user_id, google_api_key, youtube_url, drive_url, notion_url)
                VALUES (?, ?, ?, ?, ?)
            """, (session['user_id'], google_api_key, youtube_url, drive_url, notion_url))
            conn.commit()

        flash('Configuration updated successfully.', 'success')
        return redirect(url_for('dashboard'))



    with sqlite3.connect(DB_NAME) as conn:
        config = conn.execute("SELECT * FROM user_config WHERE user_id=?", (session['user_id'],)).fetchone()

    return render_template('config.html', username=session['username'], config=config)

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
