from flask import Flask, render_template, session, redirect, url_for, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from authlib.integrations.flask_client import OAuth
import random
import string
import os

# Import Logic Modules
from logic_pickpass import PickPassGame
from logic_bidwiser import BidWiserGame

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_change_this_in_prod'

# --- GOOGLE AUTH CONFIGURATION ---
# Keys provided by user
app.config['GOOGLE_CLIENT_ID'] = "58224886652-jpcqllauehf5ngpui98b29i3o6345ksr.apps.googleusercontent.com"
app.config['GOOGLE_CLIENT_SECRET'] = "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"

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

socketio = SocketIO(app)

# --- GLOBAL ROOM MANAGER ---
ROOMS = {}

def generate_room_code():
    while True:
        code = ''.join(random.choices(string.digits, k=4))
        if code not in ROOMS: return code

# --- ROUTES ---

@app.route('/')
def index():
    if session.get('user'): return redirect(url_for('room'))
    return render_template('login.html')

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    session['user'] = user_info
    session['username'] = user_info['given_name']
    return redirect(url_for('room'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/room')
def room():
    if 'user' not in session: return redirect('/')
    return render_template('game_room.html', username=session['username'], picture=session['user'].get('picture'))

@app.route('/reset_game')
def reset_game():
    code = session.get('room_code')
    if code and code in ROOMS:
        leave_room(code)
    session.pop('room_code', None)
    return redirect(url_for('room'))

# --- SOCKET EVENTS (LOBBY & MATCHMAKING) ---

@socketio.on('create_room')
def handle_create_room():
    username = session.get('username')
    code = generate_room_code()
    
    ROOMS[code] = {
        'code': code,
        'host': username,
        'game_type': None,
        'players': [username],
        'game_instance': None,
        'status': 'lobby'
    }
    join_room(code)
    session['room_code'] = code
    
    # Send host their name back to confirm identity
    emit('room_joined', {'code': code, 'players': ROOMS[code]['players'], 'host': username, 'your_name': username}) 

@socketio.on('join_room')
def handle_join_room(data):
    username = session.get('username')
    code = data['code']
    
    if code in ROOMS:
        room = ROOMS[code]
        if room['status'] != 'lobby':
            emit('error_msg', {'msg': 'Game already started!'})
            return
            
        # --- DUPLICATE NAME HANDLING ---
        original_name = username
        counter = 2
        
        # If name exists, append #2, #3, etc.
        # This loop ensures unique names even if "Ankit" and "Ankit #2" are already there
        temp_name = username
        while temp_name in room['players']:
            temp_name = f"{original_name} #{counter}"
            counter += 1
        username = temp_name
            
        # IMPORTANT: Update session with new nickname
        session['username'] = username 
        
        if username not in room['players']:
            room['players'].append(username)
            
        join_room(code)
        session['room_code'] = code
        
        # 1. Broadcast update to existing players
        socketio.emit('room_update', room, room=code)
        
        # 2. CRITICAL FIX: Send the NEW username back to the client so JS knows who it is
        emit('room_joined', {
            'code': code, 
            'players': room['players'], 
            'host': room['host'], 
            'your_name': username 
        })
    else:
        emit('error_msg', {'msg': 'Invalid Room Code'})

@socketio.on('start_game')
def handle_start_game(data):
    username = session.get('username')
    code = session.get('room_code')
    game_type = data['game_type']
    
    if code in ROOMS:
        room = ROOMS[code]
        
        # Security: Only host can start. 
        # We check if current user is the host.
        if room['host'] != username:
            return 
        
        room['game_type'] = game_type
        room['status'] = 'playing'
        
        print(f"STARTING GAME {game_type} with players: {room['players']}")
        
        # INSTANTIATE LOGIC
        if game_type == 'pickpass':
            room['game_instance'] = PickPassGame(room['players'])
        elif game_type == 'bidwiser':
            room['game_instance'] = BidWiserGame(room['players'])
            
        state = room['game_instance'].get_state()
        state['game_type'] = game_type
        socketio.emit('game_started', state, room=code)
        
        if game_type == 'pickpass':
            check_bot_turn_pickpass(room)

# --- GAMEPLAY EVENTS ---

@socketio.on('player_action')
def handle_action(data):
    username = session.get('username')
    code = session.get('room_code')
    
    if code in ROOMS:
        room = ROOMS[code]
        game = room['game_instance']
        
        if room['game_type'] == 'pickpass':
            # Security: Pass username to logic to verify turn
            state = game.play_turn(data['action'], player_name_check=username)
            state['game_type'] = 'pickpass'
            socketio.emit('update_game', state, room=code)
            check_bot_turn_pickpass(room)
            
        elif room['game_type'] == 'bidwiser':
            has_changed = game.register_move(username, int(data['card']))
            if has_changed:
                state = game.get_state()
                state['game_type'] = 'bidwiser'
                socketio.emit('update_game', state, room=code)

# --- BOT HANDLERS ---

def check_bot_turn_pickpass(room):
    game = room['game_instance']
    state = game.get_state()
    
    while not state['game_over'] and not state['players'][state['current_player']]['is_human']:
        socketio.sleep(1.0)
        action = 'take' if game.bot_move() else 'pass'
        state = game.play_turn(action)
        state['game_type'] = 'pickpass'
        socketio.emit('update_game', state, room=room['code'])

if __name__ == '__main__':
    socketio.run(app, debug=True)