import sqlite3
from flask import Flask, render_template, session, redirect, url_for, request, flash, jsonify, g
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.'
DB_PATH = os.path.join(BASE_DIR, 'game_data.sqlite')

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_this'

# --- Database helpers -------------------------------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cursor = db.cursor()

    # Player table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Player (
            player_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            age INTEGER,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    # Corrupted_points table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Corrupted_points (
            corrupted_points_id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            corrupted_points INTEGER NOT NULL DEFAULT 0,
            date_of_score TEXT NOT NULL,
            FOREIGN KEY(player_id) REFERENCES Player(player_id)
        )
    ''')

    # Mode table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Mode (
            mode_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode_type TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            corrupted_points INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(player_id) REFERENCES Player(player_id)
        )
    ''')

    db.commit()

with app.app_context():
    init_db()

# --- Helper functions -------------------------------------------------

def find_player(name):
    cur = get_db().execute('SELECT * FROM Player WHERE name = ?', (name,))
    return cur.fetchone()

def create_player(name, password, age=None):
    db = get_db()
    cur = db.cursor()
    cur.execute('INSERT INTO Player (name, password, age, created_at) VALUES (?,?,?,?)',
                (name, password, age, datetime.utcnow().isoformat()))
    db.commit()
    return cur.lastrowid

def verify_player(name, password):
    p = find_player(name)
    return p and p['password'] == password

# --- Routes -----------------------------------------------------------

@app.route('/')
def home():
    return render_template('home.html', username=session.get('user'))

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('username')  # Keep form field named 'username' for UI compatibility
        password = request.form.get('password')
        age = request.form.get('age', None)
        confirm = request.form.get('confirm_password')

        if not name or not password or not confirm:
            flash('Please fill all fields.', 'error')
            return render_template('register.html')

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')

        if find_player(name):
            flash('Name already exists!', 'error')
            return render_template('register.html')

        try:
            age = int(age) if age else None
        except:
            age = None

        create_player(name, password, age)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('username')  # Form field named 'username' for UI compatibility
        password = request.form.get('password')

        if not name or not password:
            flash('Please enter both username and password!', 'error')
            return render_template('login.html')

        if verify_player(name, password):
            session['user'] = name
            flash(f'Welcome back, {name}!', 'success')
            return redirect(url_for('menu'))

        flash('Invalid username or password!', 'error')
        return render_template('login.html')

    return render_template('login.html')

# Logout
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

# Menu (Top 5 Corrupted Points)
@app.route('/menu')
def menu():
    user = session.get('user')

    if not user:
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cur = db.execute('''
        SELECT DISTINCT cp.corrupted_points as corruption_level, m.mode_type as mode, cp.date_of_score as created_at, p.name as username
        FROM Corrupted_points cp 
        LEFT JOIN Player p ON cp.player_id = p.player_id
        LEFT JOIN Mode m ON p.player_id = m.player_id
        ORDER BY cp.corrupted_points DESC 
        LIMIT 5
    ''')
    highscores = [dict(r) for r in cur.fetchall()]

    return render_template('menu.html', username=user, highscores=highscores)

# Leaderboard page
@app.route('/leaderboard')
def leaderboard():
    if 'user' not in session:
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cur = db.execute('''
        SELECT DISTINCT cp.corrupted_points as corruption_level, m.mode_type as mode, cp.date_of_score as created_at, p.name as username
        FROM Corrupted_points cp 
        LEFT JOIN Player p ON cp.player_id = p.player_id
        LEFT JOIN Mode m ON p.player_id = m.player_id
        ORDER BY cp.corrupted_points DESC 
        LIMIT 50
    ''')

    leaderboard_data = [dict(r) for r in cur.fetchall()]
    return render_template('leaderboard.html', leaderboard=leaderboard_data)

# Play mode
@app.route('/play/<mode>')
def play(mode):
    user = session.get('user')
    if not user:
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))

    mode = mode.lower()
    if mode not in ('easy', 'medium', 'hard'):
        mode = 'medium'

    db = get_db()
    p = find_player(user)
    player_id = p['player_id']

    # Reset corrupted points when starting/retrying a game/mode
    db.execute('''
        INSERT INTO Corrupted_points (player_id, corrupted_points, date_of_score)
        VALUES (?,?,?)
    ''', (player_id, 0, datetime.utcnow().isoformat()))
    # Record mode start with zero points
    db.execute('''
        INSERT INTO Mode (mode_type, player_id, corrupted_points)
        VALUES (?,?,?)
    ''', (mode, player_id, 0))
    db.commit()

    state = {"corruption_level": 0, "exposure_meter": 0, "resources": 100}

    return render_template('game.html', username=user, mode=mode, state=state)

# Update corruption score
@app.route('/corruption', methods=['POST'])
def post_corruption():
    # Accept JSON (AJAX) or regular form POST (no JS required)
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form or {}

    username = session.get('user')

    if not username:
        return jsonify({'error': 'Not logged in'}), 401

    corruption_level = int(data.get('corruption_level') or 0)
    exposure_meter = int(data.get('exposure_meter') or 0)
    resources = int(data.get('resources') or 0)
    mode = data.get('mode', 'medium')

    p = find_player(username)
    player_id = p['player_id']

    # Scandal risk
    import random
    scandal = False
    if exposure_meter > 80 and random.random() < 0.3:
        corruption_level = max(0, corruption_level - 50)
        exposure_meter = 0
        scandal = True

    db = get_db()
    db.execute('''
        INSERT INTO Corrupted_points (player_id, corrupted_points, date_of_score)
        VALUES (?,?,?)
    ''', (player_id, corruption_level, datetime.utcnow().isoformat()))
    
    # Insert Mode record
    db.execute('''
        INSERT INTO Mode (mode_type, player_id, corrupted_points)
        VALUES (?,?,?)
    ''', (mode, player_id, corruption_level))
    
    db.commit()

    if request.is_json:
        return jsonify({'status': 'ok', 'scandal': scandal})
    else:
        flash('Score submitted', 'success')
        return redirect(url_for('menu'))

# Public API for highscores
@app.route('/api/highscores')
def api_highscores():
    db = get_db()
    cur = db.execute('''
        SELECT DISTINCT cp.corrupted_points as corruption_level, m.mode_type as mode, cp.date_of_score as created_at, p.name as username
        FROM Corrupted_points cp 
        LEFT JOIN Player p ON cp.player_id = p.player_id
        LEFT JOIN Mode m ON p.player_id = m.player_id
        ORDER BY cp.corrupted_points DESC 
        LIMIT 50
    ''')
    return jsonify([dict(r) for r in cur.fetchall()])

if __name__ == '__main__':
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    app.run(debug=True)
