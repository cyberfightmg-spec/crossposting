import os
import json
import httpx
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = os.urandom(24)

VERIFY_TOKEN = "mytoken123"
IG_PAGE_ACCESS_TOKEN = os.getenv("IG_PAGE_ACCESS_TOKEN", "")

APP_ID = os.getenv("PINTEREST_APP_ID", "1562168")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "0ff8c725a29bc17cc240104a7bf925d8db692ac0")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://leaduxai.id/web/pinterest/callback")
CALLBACK_URL = "https://leaduxai.id/web/pinterest/callback"

TOKEN_FILE = "/root/pinterest_token.json"

def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None

def save_token(data):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(data, f)

@app.route('/')
def index():
    token = get_token()
    if token:
        session['pinterest_token'] = token.get('access_token')
    return render_template('index.html')

@app.route('/login', defaults={'path': ''})
@app.route('/login/', defaults={'path': ''})
@app.route('/login/<path:path>')
def login(path):
    auth_url = (
        f"https://www.pinterest.com/oauth/?client_id={APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=boards:read,pins:read,pins:write,boards:write"
    )
    return redirect(auth_url)

@app.route('/web/pinterest/callback')
def oauth_callback():
    code = request.args.get('code')
    if not code:
        flash("No code received", "error")
        return redirect(url_for('index'))
    
    try:
        resp = httpx.post(
            "https://api.pinterest.com/v5/oauth/token",
            auth=(APP_ID, APP_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI
            }
        )
        data = resp.json()
        
        if "access_token" in data:
            save_token(data)
            session['pinterest_token'] = data.get('access_token')
            
            user_resp = httpx.get(
                "https://api.pinterest.com/v5/users/me",
                headers={"Authorization": f"Bearer {data['access_token']}"}
            )
            if user_resp.status_code == 200:
                user_data = user_resp.json()
                session['pinterest_username'] = user_data.get('username', 'User')
            
            flash("Successfully connected to Pinterest!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash(f"Error: {data.get('message', 'Unknown error')}", "error")
    except Exception as e:
        flash(f"Connection error: {e}", "error")
    
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    token = get_token()
    if not token:
        return redirect(url_for('index'))
    
    user_info = None
    boards = []
    total_boards = 0
    
    try:
        with httpx.Client() as client:
            user_resp = client.get(
                "https://api.pinterest.com/v5/users/me",
                headers={"Authorization": f"Bearer {token['access_token']}"}
            )
            if user_resp.status_code == 200:
                user_info = user_resp.json()
            
            r = client.get(
                "https://api.pinterest.com/v5/boards",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                params={"page_size": 100}
            )
            boards = r.json().get("items", [])
            total_boards = len(boards)
    except Exception as e:
        flash(f"Error fetching data: {e}", "error")
    
    return render_template('dashboard.html', 
                          boards=boards, 
                          total_boards=total_boards, 
                          total_pins=0, 
                          published_today=0,
                          user_info=user_info)

@app.route('/create')
@app.route('/create-pin', methods=['GET', 'POST'])
def create_pin():
    token = get_token()
    if not token:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        link = request.form.get('link', '')
        board_id = request.form.get('board_id', '')
        
        if 'image' not in request.files:
            flash("No image uploaded", "error")
            return redirect(url_for('create_pin'))
        
        image_file = request.files['image']
        if image_file.filename == '':
            flash("No image selected", "error")
            return redirect(url_for('create_pin'))
        
        if board_id == '':
            flash("Please select a board", "error")
            return redirect(url_for('create_pin'))
        
        # Для Trial Access - используем URL изображения вместо загрузки
        # Создаём пин с внешней ссылкой на изображение
        from tools.image_utils import fit_image
        import io
        from PIL import Image
        
        try:
            image_bytes = image_file.read()
            img = Image.open(io.BytesIO(image_bytes))
            
            # Пробуем через API
            with httpx.Client() as client:
                # Пробуем create pin с URL изображения
                # Используем базовый метод - создаём пин с ссылкой
                pin_resp = client.post(
                    "https://api.pinterest.com/v5/pins",
                    headers={
                        "Authorization": f"Bearer {token['access_token']}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "board_id": board_id,
                        "title": title[:100],
                        "description": description[:500],
                        "link": link or "https://leaduxai.id"
                    }
                )
                pin_data = pin_resp.json()
                
                if "id" in pin_data:
                    flash(f"Pin created! ID: {pin_data['id']} (без изображения - Trial API ограничение)", "success")
                else:
                    error_msg = pin_data.get('message', 'Unknown error')
                    if 'Trial' in error_msg:
                        flash("Trial Access не позволяет создавать пины с изображениями. Используйте Playwright.", "error")
                    else:
                        flash(f"Error: {error_msg}", "error")
        except Exception as e:
            flash(f"Error: {e}", "error")
    
    # Get boards for dropdown
    try:
        with httpx.Client() as client:
            r = client.get(
                "https://api.pinterest.com/v5/boards",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                params={"page_size": 100}
            )
            boards = r.json().get("items", [])
    except:
        boards = []
    
    return render_template('create_pin.html', boards=boards)

@app.route('/logout')
def logout():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    session.pop('pinterest_token', None)
    session.pop('pinterest_username', None)
    flash("Logged out", "info")
    return redirect(url_for('index'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/instagram/webhook', methods=['GET'])
def ig_webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200
    return 'Forbidden', 403

@app.route('/instagram/webhook', methods=['POST'])
def ig_webhook_handle():
    data = request.json
    print(f"Instagram webhook: {data}")
    return 'OK', 200

if __name__ == '__main__':
    os.makedirs('/root/crossposting/templates', exist_ok=True)
    app.run(host='0.0.0.0', port=5001)