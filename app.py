
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import threading, time, os, joblib
from tasks import start_background_tasks, get_latest_alerts, get_trending_rows, get_watchlist_rows, train_model_if_needed, get_stock_history_for_chart
import tasks

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'devkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = "login"
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

# ========== MODELS ==========
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Watch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)

with app.app_context():
    db.create_all()

@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('User exists', 'danger')
            return redirect(url_for('register'))
        u = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(u); db.session.commit()
        flash('Registered. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']; password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Bad credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    gainers, losers, all_rows = get_trending_rows()
    watch = get_watchlist_rows(current_user.id)
    alerts = get_latest_alerts()
    summary = 'Bullish' if sum(1 for r in all_rows if r['change']>0) > sum(1 for r in all_rows if r['change']<0) else 'Bearish'
    return render_template('index.html', gainers=gainers, losers=losers, watchlist=watch, alerts=alerts, summary=summary)

@app.route('/add_watch', methods=['POST'])
@login_required
def add_watch():
    sym = request.form['symbol'].strip().upper()
    if not sym: return redirect(url_for('dashboard'))
    if Watch.query.filter_by(user_id=current_user.id, symbol=sym).first():
        flash('Already in watchlist', 'info')
    else:
        w = Watch(user_id=current_user.id, symbol=sym); db.session.add(w); db.session.commit()
        flash('Added to watchlist', 'success')
    return redirect(url_for('dashboard'))

@app.route('/remove_watch/<int:id>')
@login_required
def remove_watch(id):
    w = Watch.query.get(id)
    if w and w.user_id==current_user.id:
        db.session.delete(w); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/search_stock')
@login_required
def search_stock():
    q = request.args.get('q','').upper().strip()
    rows = tasks.search_stocks(q)
    return jsonify(rows)

@app.route('/chart/<symbol>')
@login_required
def chart(symbol):
    data = get_stock_history_for_chart(symbol)
    return jsonify(data)

@socketio.on('connect')
def on_connect():
    emit('initial_alerts', get_latest_alerts())

threading.Thread(target=start_background_tasks, daemon=True).start()
threading.Thread(target=train_model_if_needed, daemon=True).start()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
