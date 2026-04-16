from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import hashlib
import random

app = Flask(__name__)
app.secret_key = 'banking_secret_key'

def get_db():
    conn = sqlite3.connect('bank.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0,
            account_number TEXT UNIQUE NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = hash_password(request.form['password'])
        account_number = str(random.randint(1000000000, 9999999999))
        try:
            conn = get_db()
            conn.execute('INSERT INTO users (name, email, password, account_number) VALUES (?, ?, ?, ?)',
                         (name, email, password, account_number))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return render_template('signup.html', error='Email already exists!')
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hash_password(request.form['password'])
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ? AND password = ?',
                            (email, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid email or password!')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    transactions = conn.execute(
        'SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC',
        (session['user_id'],)).fetchall()
    conn.close()
    error = request.args.get('error')
    return render_template('dashboard.html', user=user, transactions=transactions, error=error)

@app.route('/deposit', methods=['POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    amount = float(request.form['amount'])
    if amount > 0:
        conn = get_db()
        conn.execute('UPDATE users SET balance = balance + ? WHERE id = ?',
                     (amount, session['user_id']))
        conn.execute('INSERT INTO transactions (user_id, type, amount) VALUES (?, ?, ?)',
                     (session['user_id'], 'Deposit', amount))
        conn.commit()
        conn.close()
    return redirect(url_for('dashboard'))

@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    amount = float(request.form['amount'])
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if amount > 0 and amount <= user['balance']:
        conn.execute('UPDATE users SET balance = balance - ? WHERE id = ?',
                     (amount, session['user_id']))
        conn.execute('INSERT INTO transactions (user_id, type, amount) VALUES (?, ?, ?)',
                     (session['user_id'], 'Withdrawal', amount))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/transfer', methods=['POST'])
def transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    amount = float(request.form['amount'])
    to_account = request.form['to_account']
    conn = get_db()
    sender = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    receiver = conn.execute('SELECT * FROM users WHERE account_number = ?', (to_account,)).fetchone()
    if not receiver:
        conn.close()
        return redirect(url_for('dashboard', error='Account not found'))
    if receiver['id'] == session['user_id']:
        conn.close()
        return redirect(url_for('dashboard', error='Cannot transfer to yourself'))
    if amount <= 0 or amount > sender['balance']:
        conn.close()
        return redirect(url_for('dashboard', error='Invalid amount or insufficient balance'))
    conn.execute('UPDATE users SET balance = balance - ? WHERE id = ?', (amount, session['user_id']))
    conn.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, receiver['id']))
    conn.execute('INSERT INTO transactions (user_id, type, amount) VALUES (?, ?, ?)',
                 (session['user_id'], f'Transfer to {receiver["name"]}', amount))
    conn.execute('INSERT INTO transactions (user_id, type, amount) VALUES (?, ?, ?)',
                 (receiver['id'], f'Transfer from {sender["name"]}', amount))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/chart-data')
def chart_data():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    conn = get_db()
    transactions = conn.execute(
        'SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC',
        (session['user_id'],)).fetchall()
    conn.close()

    totals = {'Deposit': 0, 'Withdrawal': 0, 'Transfer': 0}
    daily = {}
    for t in transactions:
        date = t['date'][:10]
        amount = t['amount']
        tx_type = t['type']
        if 'Deposit' in tx_type:
            totals['Deposit'] += amount
        elif 'Withdrawal' in tx_type:
            totals['Withdrawal'] += amount
        else:
            totals['Transfer'] += amount
        if date not in daily:
            daily[date] = 0
        daily[date] += amount

    sorted_daily = dict(sorted(daily.items())[-7:])
    return jsonify({
        'totals': totals,
        'daily_labels': list(sorted_daily.keys()),
        'daily_data': list(sorted_daily.values())
    })

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return jsonify({'notifications': []})
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    transactions = conn.execute(
        'SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT 5',
        (session['user_id'],)).fetchall()
    conn.close()

    alerts = []
    if user['balance'] < 1000:
        alerts.append({'type': 'warning', 'message': f'Low balance! Rs {user["balance"]:.2f} remaining'})
    for t in transactions:
        if t['amount'] >= 5000:
            alerts.append({'type': 'info', 'message': f'Large transaction: {t["type"]} of Rs {t["amount"]:.2f}'})
    return jsonify({'notifications': alerts})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)