from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import time
import threading
from datetime import datetime
import random
import eventlet
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# ============================================================
# 1. EVENTLET PATCH - MUST BE FIRST!
# ============================================================
eventlet.monkey_patch()

# ============================================================
# 2. LOAD ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()

# ============================================================
# 3. CREATE FLASK APP
# ============================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ============================================================
# 4. SUPABASE SETUP
# ============================================================
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')

USE_SUPABASE = False
if SUPABASE_URL and SUPABASE_ANON_KEY:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        USE_SUPABASE = True
        print("✅ Supabase connected successfully!")
        print(f"📡 URL: {SUPABASE_URL}")
    except Exception as e:
        print(f"❌ Supabase connection error: {e}")
        print("⚠️ Continuing with simulated data only...")
else:
    print("⚠️ Supabase credentials not found in .env file")
    print("⚠️ Using simulated data only...")

# ============================================================
# 5. SENSOR DATA VARIABLES
# ============================================================
sensor_data_history = []
MAX_HISTORY = 50
current_temp = 25.0
current_humidity = 60.0
buzzer_active = False
total_readings = 0

# ============================================================
# 6. ALERT SYSTEM
# ============================================================
alert_history = []
MAX_ALERTS = 50
alert_count = 0

def add_alert(temp, humid):
    global alert_history, alert_count
    alert = {
        'id': len(alert_history) + 1,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'time': datetime.now().strftime('%I:%M:%S %p'),
        'date': datetime.now().strftime('%b %d, %Y'),
        'temperature': temp,
        'humidity': humid,
        'message': f'🔥 Temperature exceeded 38°C!',
        'status': 'unread',
        'type': 'danger'
    }
    alert_history.insert(0, alert)
    if len(alert_history) > MAX_ALERTS:
        alert_history.pop()
    alert_count += 1
    return alert

def get_unread_alerts():
    return [a for a in alert_history if a['status'] == 'unread']

# ============================================================
# 7. SETTINGS STORAGE
# ============================================================
user_settings = {
    'theme': 'dark',
    'accent_color': 'purple',
    'temperature_threshold': 38.0,
    'auto_refresh': True,
    'refresh_interval': 5,
    'chart_show_points': True,
    'chart_smooth_lines': True,
    'show_notifications': True,
    'notification_sound': True,
}

# ============================================================
# 8. SENSOR FUNCTIONS
# ============================================================
def generate_sensor_data():
    global current_temp, current_humidity, buzzer_active, total_readings
    threshold = user_settings.get('temperature_threshold', 38.0)
    if random.random() < 0.50:
        current_temp = random.uniform(threshold, threshold + 4.0)
    else:
        current_temp += random.uniform(-0.5, 0.5)
        current_temp = max(20, min(35, current_temp))
    current_humidity += random.uniform(-1, 1)
    current_humidity = max(30, min(85, current_humidity))
    buzzer_active = current_temp >= threshold
    total_readings += 1
    return round(current_temp, 1), round(current_humidity, 1)

def save_to_supabase(temp, humid, buzzer):
    if not USE_SUPABASE:
        return False
    try:
        data = {
            "timestamp": datetime.now().isoformat(),
            "temperature": temp,
            "humidity": humid,
            "buzzer_active": buzzer
        }
        result = supabase.table("sensor_readings").insert(data).execute()
        print(f"💾 Data saved to Supabase: {temp}°C, {humid}%")
        return True
    except Exception as e:
        print(f"❌ Error saving to Supabase: {e}")
        return False

def get_latest_from_supabase():
    if not USE_SUPABASE:
        return None
    try:
        result = supabase.table("sensor_readings").select("*").order('created_at', desc=True).limit(1).execute()
        if result.data:
            row = result.data[0]
            return {
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'timestamp': row['timestamp'][11:16] if row['timestamp'] else '--:--',
                'buzzer_active': row['buzzer_active']
            }
    except Exception as e:
        print(f"❌ Error fetching from Supabase: {e}")
    return None

def get_history_from_supabase(limit=50):
    if not USE_SUPABASE:
        return []
    try:
        result = supabase.table("sensor_readings").select("*").order('created_at', desc=False).limit(limit).execute()
        history = []
        for row in result.data:
            history.append({
                'timestamp': row['timestamp'][11:16] if row['timestamp'] else '--:--',
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'datetime': row['timestamp']
            })
        return history
    except Exception as e:
        print(f"❌ Error fetching history from Supabase: {e}")
        return []

def get_stats_from_supabase():
    if not USE_SUPABASE:
        return None
    try:
        result = supabase.table("sensor_readings").select("*").execute()
        if not result.data:
            return None
        temps = [row['temperature'] for row in result.data]
        humids = [row['humidity'] for row in result.data]
        alerts = sum(1 for row in result.data if row.get('buzzer_active', False))
        return {
            'total_readings': len(result.data),
            'avg_temp': round(sum(temps) / len(temps), 1),
            'min_temp': round(min(temps), 1),
            'max_temp': round(max(temps), 1),
            'avg_humid': round(sum(humids) / len(humids), 1),
            'min_humid': round(min(humids), 1),
            'max_humid': round(max(humids), 1),
            'alert_count': alerts
        }
    except Exception as e:
        print(f"❌ Error getting stats from Supabase: {e}")
        return None

def sensor_loop():
    global sensor_data_history, current_temp, current_humidity, buzzer_active, total_readings
    while True:
        try:
            temp, humid = generate_sensor_data()
            current_temp = temp
            current_humidity = humid
            threshold = user_settings.get('temperature_threshold', 38.0)
            buzzer_active = temp >= threshold
            if buzzer_active:
                alert = add_alert(temp, humid)
                socketio.emit('new_alert', alert)
            if USE_SUPABASE:
                save_to_supabase(temp, humid, buzzer_active)
            data_point = {
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'temperature': temp,
                'humidity': humid,
                'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            sensor_data_history.append(data_point)
            if len(sensor_data_history) > MAX_HISTORY:
                sensor_data_history.pop(0)
            socketio.emit('sensor_update', {
                'temperature': temp,
                'humidity': humid,
                'timestamp': data_point['timestamp'],
                'buzzer_active': buzzer_active,
                'alert_count': alert_count,
                'total_readings': total_readings
            })
            print(f"Temp: {temp}°C, Humidity: {humid}%, Buzzer: {'ON' if buzzer_active else 'OFF'}")
            time.sleep(5)
        except Exception as e:
            print(f"Error in sensor loop: {e}")
            time.sleep(5)

# ============================================================
# 9. ROUTES
# ============================================================
@app.route('/')
def landing():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/data')
def get_data():
    if USE_SUPABASE:
        supabase_data = get_latest_from_supabase()
        if supabase_data:
            return jsonify({
                'temperature': supabase_data['temperature'],
                'humidity': supabase_data['humidity'],
                'timestamp': supabase_data['timestamp'],
                'buzzer_active': supabase_data['buzzer_active'],
                'alert_count': alert_count,
                'total_readings': total_readings
            })
    return jsonify({
        'temperature': current_temp,
        'humidity': current_humidity,
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'buzzer_active': buzzer_active,
        'alert_count': alert_count,
        'total_readings': total_readings
    })

@app.route('/api/history')
def get_history():
    if USE_SUPABASE:
        history = get_history_from_supabase(50)
        if history:
            return jsonify(history)
    return jsonify(sensor_data_history)

@app.route('/api/stats')
def get_stats():
    if USE_SUPABASE:
        stats = get_stats_from_supabase()
        if stats:
            return jsonify(stats)
    if sensor_data_history:
        temps = [d['temperature'] for d in sensor_data_history]
        humids = [d['humidity'] for d in sensor_data_history]
        return jsonify({
            'total_readings': len(sensor_data_history),
            'avg_temp': round(sum(temps) / len(temps), 1),
            'min_temp': round(min(temps), 1),
            'max_temp': round(max(temps), 1),
            'avg_humid': round(sum(humids) / len(humids), 1),
            'min_humid': round(min(humids), 1),
            'max_humid': round(max(humids), 1),
            'alert_count': alert_count
        })
    return jsonify({'total_readings': 0})

@app.route('/api/alerts')
def get_alerts():
    return jsonify(alert_history)

@app.route('/api/alerts/unread/count')
def get_unread_count():
    return jsonify({'count': len(get_unread_alerts())})

@app.route('/api/alerts/mark_read', methods=['POST'])
def mark_alerts_read():
    global alert_history
    for alert in alert_history:
        alert['status'] = 'read'
    return jsonify({'success': True})

@app.route('/api/alerts/clear', methods=['POST'])
def clear_alerts():
    global alert_history, alert_count
    alert_history = []
    alert_count = 0
    return jsonify({'success': True})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    global user_settings
    if request.method == 'GET':
        return jsonify(user_settings)
    elif request.method == 'POST':
        data = request.json
        for key, value in data.items():
            if key in user_settings:
                user_settings[key] = value
        return jsonify({'success': True, 'settings': user_settings})

@app.route('/api/settings/reset', methods=['POST'])
def reset_settings():
    global user_settings
    user_settings = {
        'theme': 'dark',
        'accent_color': 'purple',
        'temperature_threshold': 38.0,
        'auto_refresh': True,
        'refresh_interval': 5,
        'chart_show_points': True,
        'chart_smooth_lines': True,
        'show_notifications': True,
        'notification_sound': True,
    }
    return jsonify({'success': True, 'settings': user_settings})

# ============================================================
# 10. RUN THE APP
# ============================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)