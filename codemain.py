from flask import Flask, render_template_string, request, jsonify, redirect, session
import firebase_admin
from firebase_admin import credentials, db
import requests
import google.generativeai as genai
from datetime import datetime
import os
import json

app = Flask(__name__)
app.secret_key = "bunhin2025_strong_secret_key_123456789"

@app.after_request
def add_security_headers(response):
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
    return response

# ================== Firebase Admin ==================
firebase_json_str = os.environ.get("FIREBASE_KEY")
if not firebase_json_str:
    raise ValueError("❌ Missing FIREBASE_KEY environment variable")

cred = credentials.Certificate(json.loads(firebase_json_str))
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bunhin-60375-default-rtdb.asia-southeast1.firebasedatabase.app'
})

# ================== API KEYS ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")

if not GEMINI_API_KEY or not WEATHER_API_KEY:
    raise ValueError("❌ Missing GEMINI_API_KEY or WEATHER_API_KEY")

DEFAULT_LAT = 10.255698718281469
DEFAULT_LNG = 106.36672811453062

# ================== Khởi tạo Gemini với system_instruction có dữ liệu realtime ==================
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",   # Model nhẹ, quota cao hơn, ít lỗi hơn
    system_instruction="""
    Bạn là Bù Nhìn 5.0 - chuyên gia nông nghiệp miền Nam Việt Nam (Đồng Bằng Sông Cửu Long).
    Nói tiếng Việt, gần gũi, dễ hiểu, thực tế như đang nói chuyện với bà con nông dân.
    Tập trung tư vấn về trồng lúa, cây ăn trái (xoài, sầu riêng, thanh long, chôm chôm...), sâu bệnh, phân bón, tưới tiêu, thời vụ, giống cây.

    Dữ liệu realtime từ ruộng của bà con (luôn xem xét dữ liệu này khi trả lời):
    - Nhiệt độ không khí
    - Độ ẩm không khí
    - Độ ẩm đất
    - Ánh sáng (lux)
    - Trạng thái mưa
    - Thời tiết khu vực hiện tại

    Trả lời ngắn gọn, đưa mẹo hay, dễ làm theo. Nếu không chắc chắn thì khuyên bà con hỏi thêm trạm khuyến nông địa phương.
    Không dùng ký tự đặc biệt lạ, không dùng markdown, không dùng dấu *.
    """
)

# ================== HTML TEMPLATE (giữ nguyên, chỉ bổ sung tab4 đầy đủ) ==================
HTML_TEMPLATE = ''' 
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🌾 Bù Nhìn 5.0</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js"></script>
  <script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-auth-compat.js"></script>
  <script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-database-compat.js"></script>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body { font-family: system-ui; }
    .login-bg { background: linear-gradient(135deg, #10b981, #15803d); }
    .login-card { background: white; border-radius: 28px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); }
    .google-btn { transition: all 0.3s ease; }
    .google-btn:hover { transform: translateY(-3px); box-shadow: 0 15px 30px rgba(16,185,129,0.35); }

    /* Sidebar - desktop mặc định */
    .sidebar {
      width: 270px;
      background: white;
      box-shadow: 3px 0 15px rgba(0,0,0,0.1);
      position: fixed;
      top: 0; left: 0; bottom: 0;
      z-index: 100;
      transition: transform 0.3s ease;
      display: flex;
      flex-direction: column;
    }
    .main-content { margin-left: 270px; }

    /* Overlay cho mobile */
    #sidebar-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.4);
      z-index: 99;
    }
    #sidebar-overlay.active { display: block; }

    /* Hamburger button - ẩn trên desktop */
    #hamburger {
      display: none;
      position: fixed;
      top: 12px; left: 12px;
      z-index: 200;
      background: #10b981;
      color: white;
      border: none;
      border-radius: 12px;
      width: 44px; height: 44px;
      font-size: 22px;
      cursor: pointer;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(16,185,129,0.4);
    }

    /* Tab content */
    .tab { display: none; }
    .tab.active { display: block; }

    /* Map height */
    #map {
      height: 480px;
      border-radius: 20px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.15);
      z-index: 1;        /* thấp hơn sidebar (100) và overlay (99) */
      position: relative;
    }
    /* Leaflet controls cũng giữ z-index thấp */
    .leaflet-top, .leaflet-bottom { z-index: 2 !important; }

    .menu-btn { transition: all 0.3s ease; }
    .menu-btn:hover { background-color: #f0fdf4; transform: translateX(8px); }
    .menu-btn.active { background-color: #10b981; color: white; font-weight: 600; }
    .chat-window { height: 420px; overflow-y: auto; padding: 20px; background: #f0fdf4; border-radius: 16px; }
    .chat-bubble-user { background: #10b981; color: white; border-radius: 20px 20px 0 20px; padding: 12px 16px; }
    .chat-bubble-ai { background: white; border: 1px solid #e5e7eb; border-radius: 20px 20px 20px 0; padding: 12px 16px; }

    /* ============ MOBILE (<= 768px) ============ */
    @media (max-width: 768px) {
      /* Sidebar ẩn bên trái, kéo ra khi mở */
      .sidebar {
        transform: translateX(-100%);
      }
      .sidebar.open {
        transform: translateX(0);
      }

      /* Nội dung chiếm toàn màn hình */
      .main-content {
        margin-left: 0;
        padding-top: 64px; /* chừa chỗ cho hamburger */
      }

      /* Hiện hamburger */
      #hamburger { display: flex; }

      /* Map thấp hơn trên mobile */
      #map { height: 280px; border-radius: 14px; }

      /* Sensor cards: font nhỏ lại, không tràn ô */
      .sensor-card { padding: 14px !important; }
      .sensor-value {
        font-size: 1.8rem !important;
        line-height: 1.2 !important;
        word-break: break-all;
        margin-top: 8px !important;
      }
      .sensor-label { font-size: 0.8rem !important; }

      /* Chat: input không bị cắt */
      .chat-input-row {
        flex-direction: row !important;
        gap: 8px !important;
      }
      .chat-input-row input {
        min-width: 0;
        font-size: 14px !important;
        padding: 12px !important;
      }
      .chat-input-row button {
        flex-shrink: 0;
        padding: 12px 16px !important;
        font-size: 14px !important;
      }

      /* Chat ngắn hơn */
      .chat-window { height: 300px; padding: 12px; font-size: 14px; }

      /* Heading nhỏ hơn */
      .main-content h2 { font-size: 1.4rem !important; margin-bottom: 1rem !important; }

      /* Padding nội dung */
      .main-content > div > .tab { padding: 0; }
    }
  </style>
</head>
<body>

  {% if not user %}
  <div class="login-bg min-h-screen flex items-center justify-center p-6">
    <div class="login-card w-full max-w-md p-10 text-center">
      <div class="mx-auto w-20 h-20 bg-green-100 rounded-3xl flex items-center justify-center text-6xl mb-6">🌾</div>
      <h1 class="text-4xl font-bold text-green-700 mb-1">Bù Nhìn 5.0 - Giải pháp bảo vệ mùa màng bền vững cho nhà nông</h1>
      <p class="text-green-600 mb-8">Bảo vệ mùa màng thông minh cho bà con</p>
      <button onclick="loginWithGoogle()" class="google-btn w-full bg-white border border-gray-200 hover:border-green-500 text-gray-700 font-medium py-5 px-6 rounded-2xl flex items-center justify-center gap-4 text-lg shadow">
        <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Google_Favicon_2025.svg/1280px-Google_Favicon_2025.svg.png" alt="Google" class="w-7 h-7">
        Đăng nhập bằng Google
      </button>
    </div>
  </div>
  {% else %}

  <!-- Hamburger button (chỉ hiện trên mobile) -->
  <button id="hamburger" onclick="toggleSidebar()">☰</button>
  <!-- Overlay tối khi sidebar mở trên mobile -->
  <div id="sidebar-overlay" onclick="closeSidebar()"></div>

  <div class="flex min-h-screen">
    <div class="sidebar" id="sidebar">
      <div class="flex flex-col h-full">
      <div class="p-6 border-b bg-green-50">
        <h1 class="text-2xl font-bold text-green-700 flex items-center gap-2">🌾 Bù Nhìn 5.0</h1>
        <p class="text-green-600 text-sm mt-1">Nông nghiệp thông minh</p>
      </div>
      <div class="px-6 py-5 border-b">
        <p class="text-sm text-gray-500">Xin chào</p>
        <p class="font-semibold text-green-700 truncate">{{ user['email'] }}</p>
      </div>
      <div class="px-6 py-5 border-b">
        <p class="text-xs font-medium text-gray-500 mb-2">THIẾT BỊ HIỆN TẠI</p>
        <div class="flex items-center gap-2 mb-3">
          <span class="inline-block w-2 h-2 rounded-full bg-green-500"></span>
          <span id="current_device_label" class="font-semibold text-green-700 text-sm">{{ current_device }}</span>
        </div>
        <select id="device_select" onchange="switchDevice(this.value)"
          class="w-full px-3 py-2 border border-gray-300 rounded-2xl text-sm focus:outline-none focus:border-green-500 mb-1 bg-white">
          <option value="{{ current_device }}">{{ current_device }}</option>
        </select>
        <p class="text-xs text-gray-400">Chọn để chuyển thiết bị</p>
      </div>
      <div class="px-6 py-5 border-b">
        <p class="text-xs font-medium text-gray-500 mb-2">ĐĂNG KÝ THIẾT BỊ MỚI</p>
        <input id="device_id" type="text" placeholder="BN5001" class="w-full px-4 py-3 border border-gray-300 rounded-2xl text-sm focus:outline-none focus:border-green-500 mb-3">
        <button onclick="claimDevice()" class="w-full bg-green-600 hover:bg-green-700 text-white py-3 rounded-2xl text-sm font-medium">Đăng ký</button>
      </div>
      <div class="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
        <button onclick="openTab(2)" id="tabBtn2" class="menu-btn active w-full text-left px-5 py-4 rounded-2xl flex items-center gap-3 text-base">🗺️ Bản đồ & Thời tiết</button>
        <button onclick="openTab(1)" id="tabBtn1" class="menu-btn w-full text-left px-5 py-4 rounded-2xl flex items-center gap-3 text-base">📊 Cảm biến Realtime</button>
        <button onclick="openTab(4)" id="tabBtn4" class="menu-btn w-full text-left px-5 py-4 rounded-2xl flex items-center gap-3 text-base">🎛️ Điều khiển Bù Nhìn</button>
        <button onclick="openTab(5)" id="tabBtn5" class="menu-btn w-full text-left px-5 py-4 rounded-2xl flex items-center gap-3 text-base">🤖 AI Tư vấn</button>
      </div>
      <div class="p-6 border-t">
        <button onclick="logout()" class="w-full py-3.5 bg-red-500 hover:bg-red-600 text-white rounded-2xl font-medium">Đăng xuất</button>
      </div>
      </div><!-- end flex flex-col h-full -->
    </div><!-- end sidebar -->

    <div class="main-content flex-1 p-4 md:p-8 bg-gray-50 overflow-auto min-h-screen">
      <!-- Tab 2: Bản đồ -->
      <div id="tab2" class="tab active">
        <h2 class="text-3xl font-bold text-green-800 mb-6">🗺️ Bản đồ Vệ tinh Ruộng</h2>
        <div id="map"></div>
        <div id="weather_info" class="mt-6 bg-white p-6 rounded-3xl shadow"></div>
      </div>

      <!-- Tab 1: Cảm biến -->
      <div id="tab1" class="tab">
        <h2 class="text-3xl font-bold text-green-800 mb-8">📊 Cảm biến Realtime</h2>
        <div class="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
          <div class="sensor-card bg-white p-6 rounded-3xl shadow"><p class="sensor-label text-gray-500">🌡️ Nhiệt độ</p><p id="temp" class="sensor-value text-5xl font-bold text-orange-600 mt-4">--- °C</p></div>
          <div class="sensor-card bg-white p-6 rounded-3xl shadow"><p class="sensor-label text-gray-500">💧 Độ ẩm KK</p><p id="hum" class="sensor-value text-5xl font-bold text-blue-600 mt-4">--- %</p></div>
          <div class="sensor-card bg-white p-6 rounded-3xl shadow"><p class="sensor-label text-gray-500">☀️ Ánh sáng</p><p id="lux" class="sensor-value text-5xl font-bold text-yellow-600 mt-4">--- lux</p></div>
          <div class="sensor-card bg-white p-6 rounded-3xl shadow"><p class="sensor-label text-gray-500">🌧️ Mưa</p><p id="rain" class="sensor-value text-5xl font-bold text-cyan-600 mt-4">---</p></div>
          <div class="sensor-card bg-white p-6 rounded-3xl shadow"><p class="sensor-label text-gray-500">🌱 Độ ẩm đất</p><p id="soil" class="sensor-value text-5xl font-bold text-emerald-600 mt-4">--- %</p></div>
        </div>
      </div>

      <!-- Tab 4: Điều khiển Bù Nhìn (đã bổ sung đầy đủ) -->
      <div id="tab4" class="tab">
        <h2 class="text-3xl font-bold text-green-800 mb-8">🎛️ Điều khiển Bù Nhìn</h2>
        <div class="bg-white p-8 rounded-3xl shadow space-y-12">
          <div>
            <h3 class="font-semibold text-lg mb-4 flex items-center gap-2">☀️ Ban ngày</h3>
            <div class="flex items-center gap-3 mb-6">
              <input type="checkbox" id="dayEnabled" checked onchange="sendCommand('SET_DAY_ENABLED=' + (this.checked ? '1' : '0'))" class="w-5 h-5 accent-green-600">
              <label class="font-medium">Bật phát âm thanh ban ngày</label>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <label class="block text-sm font-medium mb-2">Âm lượng (0-30)</label>
                <input type="range" id="volume" min="0" max="30" value="25" class="w-full accent-green-600" oninput="sendCommand('SET_VOLUME='+this.value)">
              </div>
              <div>
                <label class="block text-sm font-medium mb-2">Bài hát</label>
                <select id="song" onchange="sendCommand('SET_SONG='+this.value)" class="w-full p-3 border rounded-2xl">
                  <option value="1">001 - Tiếng chim sắc sắc</option>
                  <option value="2">002 - Tiếng đại bàng</option>
                  <option value="3">003 - Tiếng cú mèo</option>
                  <option value="4">004 - Tiếng diều trắng</option>
                  <option value="5">005 - Tiếng chim ưng</option>
                  <option value="6">006 - Tiếng chó sủa</option>
                  <option value="7">007 - Tiếng kền kền</option>
                  <option value="8">008 - Tiếng chồn</option>
                  <option value="9">009 - Tiếng rắn rít nguy hiểm</option>
                  <option value="10">010 - Tiếng mèo meo meo</option>
                </select>
              </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-6 mt-8">
              <div>
                <label class="block text-sm font-medium mb-2">Thời gian phát (giây)</label>
                <input type="number" id="activeTime" value="10" min="1" class="w-full p-3 border border-gray-300 rounded-2xl text-center" oninput="sendCommand('SET_ACTIVE=' + this.value)">
              </div>
              <div>
                <label class="block text-sm font-medium mb-2">Thời gian nghỉ (giây)</label>
                <input type="number" id="restTime" value="20" min="5" class="w-full p-3 border border-gray-300 rounded-2xl text-center" oninput="sendCommand('SET_REST=' + this.value)">
              </div>
            </div>
          </div>

          <div>
            <h3 class="font-semibold text-lg mb-4 flex items-center gap-2">🌙 Ban đêm</h3>
            <div class="flex items-center gap-3 mb-6">
              <input type="checkbox" id="nightEnabled" onchange="sendCommand('SET_NIGHT_ENABLED=' + (this.checked ? '1' : '0'))" class="w-5 h-5 accent-green-600">
              <label class="font-medium">Bật phát âm thanh ban đêm</label>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <label class="block text-sm font-medium mb-2">Bài hát ban đêm</label>
                <select id="nightSong" onchange="sendCommand('SET_NIGHT_SONG='+this.value)" class="w-full p-3 border rounded-2xl">
                  <option value="1">001 - Tiếng chim sắc sắc</option>
                  <option value="2">002 - Tiếng đại bàng</option>
                  <option value="3">003 - Tiếng cú mèo</option>
                  <option value="4">004 - Tiếng diều trắng</option>
                  <option value="5">005 - Tiếng chim ưng</option>
                  <option value="6">006 - Tiếng chó sủa</option>
                  <option value="7">007 - Tiếng kền kền</option>
                  <option value="8">008 - Tiếng chồn</option>
                  <option value="9">009 - Tiếng rắn rít nguy hiểm</option>
                  <option value="10">010 - Tiếng mèo meo meo</option>
                </select>
              </div>
              <div>
                <label class="block text-sm font-medium mb-2">Âm lượng ban đêm (0-30)</label>
                <input type="range" id="nightVolume" min="0" max="30" value="15" class="w-full accent-green-600" oninput="sendCommand('SET_NIGHT_VOLUME='+this.value)">
              </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-6 mt-8">
              <div>
                <label class="block text-sm font-medium mb-2">Thời gian phát đêm (giây)</label>
                <input type="number" id="nightActiveTime" value="10" min="1" class="w-full p-3 border border-gray-300 rounded-2xl text-center" oninput="sendCommand('SET_NIGHT_ACTIVE=' + this.value)">
              </div>
              <div>
                <label class="block text-sm font-medium mb-2">Thời gian nghỉ đêm (giây)</label>
                <input type="number" id="nightRestTime" value="20" min="5" class="w-full p-3 border border-gray-300 rounded-2xl text-center" oninput="sendCommand('SET_NIGHT_REST=' + this.value)">
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 5: AI -->
      <div id="tab5" class="tab">
        <h2 class="text-3xl font-bold text-green-800 mb-6">🤖 AI Tư vấn Nông nghiệp</h2>
        <div class="bg-white rounded-3xl shadow p-6">
          <div id="chat_window" class="chat-window flex flex-col gap-4"></div>
          <div class="chat-input-row flex gap-3 mt-4">
            <input id="chat_input" type="text" placeholder="Hỏi về cây trồng, sâu bệnh, pH đất..." 
                   class="flex-1 min-w-0 px-4 py-3 border border-gray-300 rounded-2xl focus:outline-none focus:border-green-500 text-sm"
                   onkeypress="if(event.key === 'Enter') sendChatMessage()">
            <button onclick="sendChatMessage()" class="flex-shrink-0 bg-green-600 hover:bg-green-700 text-white px-5 py-3 rounded-2xl font-medium text-sm">Gửi</button>
          </div>
        </div>
      </div>
    </div>
  </div>
  {% endif %}

  <script>
    // Firebase config
    firebase.initializeApp({
      apiKey: "AIzaSyCHSsED9kVe0wqu82UyD3MpW0tc3Hrr1UA",
      authDomain: "bunhin-60375.firebaseapp.com",
      databaseURL: "https://bunhin-60375-default-rtdb.asia-southeast1.firebasedatabase.app",
      projectId: "bunhin-60375"
    });

    const auth = firebase.auth();
    const database = firebase.database();

    let map = null;
    let marker = null;

    function loginWithGoogle() {
      const provider = new firebase.auth.GoogleAuthProvider();
      auth.signInWithPopup(provider).then(result => {
        window.location.href = `/set_session?uid=${result.user.uid}&email=${encodeURIComponent(result.user.email)}`;
      }).catch(error => alert("Đăng nhập thất bại: " + error.message));
    }

    function logout() { auth.signOut().then(() => window.location.href = '/logout'); }

    // ===== DEVICE MANAGEMENT =====
    let currentDevice = "{{ current_device }}";
    let sensorListener = null;

    function switchDevice(deviceId) {
      if (!deviceId) return;
      fetch('/select_device', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device_id: deviceId})
      }).then(r => r.json()).then(d => {
        if (d.status === 'ok') {
          currentDevice = d.current_device;
          document.getElementById('current_device_label').textContent = currentDevice;
          // Tắt listener cũ, bật listener mới
          if (sensorListener) sensorListener.off();
          startSensorListener();
        }
      });
    }

    function loadDeviceList() {
      fetch('/get_devices').then(r => r.json()).then(d => {
        const sel = document.getElementById('device_select');
        if (!sel) return;
        sel.innerHTML = '';
        (d.devices || [{id: 'BN5001', name: 'BN5001'}]).forEach(dev => {
          const opt = document.createElement('option');
          opt.value = dev.id;
          opt.textContent = dev.name !== dev.id ? dev.name + ' (' + dev.id + ')' : dev.id;
          if (dev.id === d.current) opt.selected = true;
          sel.appendChild(opt);
        });
        document.getElementById('current_device_label').textContent = d.current || 'BN5001';
      }).catch(() => {});
    }

    function startSensorListener() {
      sensorListener = database.ref('/devices/' + currentDevice + '/sensors');
      sensorListener.on('value', (snap) => {
        const d = snap.val() || {};
        if (d.lat && d.lon && marker) marker.setLatLng([d.lat, d.lon]);
        if (d.lat && d.lon && map) map.flyTo([d.lat, d.lon], 16);
        document.getElementById('temp').textContent = (d.temp || '---') + ' °C';
        document.getElementById('hum').textContent = (d.hum || '---') + ' %';
        document.getElementById('lux').textContent = (d.lux || '---') + ' lux';
        document.getElementById('soil').textContent = (d.soil || '---') + ' %';
        document.getElementById('rain').textContent = d.rain > 2000 ? 'Không mưa' : 'Có mưa';
      });
    }

    function initMap() {
      map = L.map('map').setView([{{ DEFAULT_LAT }}, {{ DEFAULT_LNG }}], 15);
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom: 19}).addTo(map);
      marker = L.marker([{{ DEFAULT_LAT }}, {{ DEFAULT_LNG }}], {draggable: true}).addTo(map)
        .bindPopup("Vị trí ruộng - Kéo để chỉnh");
      marker.on('dragend', (e) => {
        const pos = e.target.getLatLng();
        database.ref('/devices/' + currentDevice + '/location').set({lat: pos.lat, lng: pos.lng, timestamp: Date.now()});
      });
    }

    startSensorListener();

    function fetchWeather() {
      fetch(`https://api.openweathermap.org/data/2.5/weather?lat={{ DEFAULT_LAT }}&lon={{ DEFAULT_LNG }}&appid={{ WEATHER_API_KEY }}&units=metric&lang=vi`)
        .then(r => r.json())
        .then(data => {
          const html = `<div class="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Nhiệt độ</div><div class="text-3xl font-bold">${Math.round(data.main.temp)}°C</div></div>
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Thời tiết</div><div class="text-xl">${data.weather[0].description}</div></div>
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Độ ẩm KK</div><div class="text-3xl font-bold">${data.main.humidity}%</div></div>
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Gió</div><div class="text-xl">${data.wind.speed} m/s</div></div>
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Áp suất</div><div class="text-xl">${data.main.pressure} hPa</div></div>
            <div class="bg-gray-50 p-4 rounded-2xl"><div class="text-sm text-gray-500">Tầm nhìn</div><div class="text-xl">${((data.visibility || 10000)/1000).toFixed(1)} km</div></div>
          </div>`;
          document.getElementById('weather_info').innerHTML = html;
        })
        .catch(() => document.getElementById('weather_info').innerHTML = '<p class="text-red-500">Không lấy được dữ liệu thời tiết</p>');
    }

    function openTab(n) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.getElementById('tab' + n).classList.add('active');
      document.querySelectorAll('.menu-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('tabBtn' + n).classList.add('active');

      // Đóng sidebar trên mobile khi chọn tab
      closeSidebar();

      if (n === 2 && !map) setTimeout(() => { initMap(); fetchWeather(); }, 150);
      if (n === 5) {
        const chat = document.getElementById('chat_window');
        if (chat.children.length === 0) {
          chat.innerHTML = `<div class="flex justify-start mb-4"><div class="chat-bubble-ai">Chào bạn! Mình là Bù nhìn 5.0 đây. Mình luôn sẵn sàng hỗ trợ bạn mọi lúc. Hôm nay đồng ruộng của bạn thế nào? Hãy nói cho mình biết và hỏi bất cứ điều gì về nông nghiệp nhé🌾</div></div>`;
        }
      }
    }

    function toggleSidebar() {
      const sidebar = document.getElementById('sidebar');
      const overlay = document.getElementById('sidebar-overlay');
      const hamburger = document.getElementById('hamburger');
      sidebar.classList.toggle('open');
      overlay.classList.toggle('active');
      // Ẩn nút ☰ khi sidebar mở, hiện lại khi đóng
      hamburger.classList.toggle('sidebar-open', sidebar.classList.contains('open'));
    }

    function closeSidebar() {
      const sidebar = document.getElementById('sidebar');
      const overlay = document.getElementById('sidebar-overlay');
      const hamburger = document.getElementById('hamburger');
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
      hamburger.classList.remove('sidebar-open');
    }

    function claimDevice() {
      const id = document.getElementById('device_id').value.trim();
      if (!id) return alert("Vui lòng nhập mã thiết bị!");
      fetch('/claim_device', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({device_id: id})})
        .then(r => r.json()).then(d => {
          alert(d.message || "Đã đăng ký");
          if (d.status === 'success') loadDeviceList();
        });
    }

    function sendCommand(cmd) {
      database.ref('/devices/' + currentDevice + '/commands').set(cmd);
    }

    function sendChatMessage() {
      const input = document.getElementById('chat_input');
      const message = input.value.trim();
      if (!message) return;

      const chatWindow = document.getElementById('chat_window');
      chatWindow.innerHTML += `<div class="flex justify-end mb-4"><div class="chat-bubble-user">${message}</div></div>`;
      chatWindow.scrollTop = chatWindow.scrollHeight;
      input.value = '';

      fetch('/get_ai_advice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query: message})
      })
      .then(r => r.json())
      .then(data => {
        chatWindow.innerHTML += `<div class="flex justify-start mb-4"><div class="chat-bubble-ai">${data.advice}</div></div>`;
        chatWindow.scrollTop = chatWindow.scrollHeight;
      })
      .catch(() => {
        chatWindow.innerHTML += `<div class="flex justify-start mb-4"><div class="chat-bubble-ai text-red-600">❌ Lỗi kết nối AI. Vui lòng thử lại sau.</div></div>`;
        chatWindow.scrollTop = chatWindow.scrollHeight;
      });
    }

    window.onload = () => { openTab(2); loadDeviceList(); };
  </script>
</body>
</html>
'''

# ================== HELPER ==================
def get_current_device():
    """Trả về thiết bị đang được chọn. Fallback về BN5001 nếu chưa chọn."""
    return session.get('current_device', 'BN5001')

# ================== ROUTES ==================
@app.route('/')
def home():
    user = session.get('user')
    current_device = get_current_device()
    return render_template_string(HTML_TEMPLATE, user=user, WEATHER_API_KEY=WEATHER_API_KEY,
                                  DEFAULT_LAT=DEFAULT_LAT, DEFAULT_LNG=DEFAULT_LNG,
                                  current_device=current_device)

@app.route('/get_ai_advice', methods=['POST'])
def get_ai_advice():
    data = request.get_json() or {}
    query = data.get('query', '')

    current_device = get_current_device()
    sensors = db.reference(f'/devices/{current_device}/sensors').get() or {}
    location = db.reference(f'/devices/{current_device}/location').get() or {}

    weather_str = "không lấy được"
    try:
        lat = sensors.get('lat') or location.get('lat') or DEFAULT_LAT
        lng = sensors.get('lon') or location.get('lng') or DEFAULT_LNG
        w = requests.get(f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={WEATHER_API_KEY}&units=metric&lang=vi", timeout=6).json()
        weather_str = f"{w['weather'][0]['description']}, {w['main']['temp']}°C, độ ẩm {w['main']['humidity']}%"
    except:
        pass

    current_time = datetime.now().strftime("%H:%M ngày %d/%m/%Y")

    # Prompt ngắn gọn vì dữ liệu đã có trong system_instruction
    prompt = f"""Thời gian hiện tại: {current_time}
Dữ liệu ruộng:
- Nhiệt độ: {sensors.get('temp', '---')}°C
- Độ ẩm KK: {sensors.get('hum', '---')}%
- Độ ẩm đất: {sensors.get('soil', '---')}%
- Ánh sáng: {sensors.get('lux', '---')} lux
- Mưa: {'Có mưa' if sensors.get('rain', 3000) < 2000 else 'Không mưa'}
- Thời tiết: {weather_str}

Câu hỏi: "{query}" """

    try:
        chat = model.start_chat(history=[])
        response = chat.send_message(prompt)
        advice = response.text.strip()
    except Exception as e:
        print("Gemini Error:", e)
        advice = "❌ Xin lỗi, AI đang bận do quota. Vui lòng chờ 30-60 giây rồi thử lại nhé!"

    return jsonify({"advice": advice})

@app.route('/set_session')
def set_session():
    uid = request.args.get('uid')
    email = request.args.get('email')
    if uid and email:
        session['user'] = {'uid': uid, 'email': email}
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/get_devices')
def get_devices():
    """Trả về danh sách thiết bị của user hiện tại (từ users/{uid}/devices)."""
    if 'user' not in session:
        return jsonify({"status": "error", "devices": [], "current": "BN5001"}), 401
    uid = session['user']['uid']
    try:
        raw = db.reference(f'users/{uid}/devices').get() or {}
        device_ids = list(raw.keys()) if isinstance(raw, dict) else []
    except Exception:
        device_ids = []
    # Fallback: nếu không có thiết bị nào thì vẫn trả về BN5001
    if not device_ids:
        device_ids = ['BN5001']
    current = get_current_device()
    # Lấy thêm tên thiết bị nếu có (field name tuỳ chọn, không bắt buộc)
    devices_info = []
    for did in device_ids:
        try:
            name = db.reference(f'devices/{did}/name').get() or did
        except Exception:
            name = did
        devices_info.append({"id": did, "name": name})
    return jsonify({"status": "ok", "devices": devices_info, "current": current})

@app.route('/select_device', methods=['POST'])
def select_device():
    """Lưu thiết bị được chọn vào session."""
    if 'user' not in session:
        return jsonify({"status": "error", "message": "Chưa đăng nhập"}), 401
    data = request.get_json() or {}
    device_id = data.get('device_id', 'BN5001').strip() or 'BN5001'
    session['current_device'] = device_id
    # Ghi last_seen nếu muốn (tuỳ chọn, không bắt buộc)
    try:
        db.reference(f'devices/{device_id}/last_seen').set(
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    except Exception:
        pass
    return jsonify({"status": "ok", "current_device": device_id})

@app.route('/claim_device', methods=['POST'])
def claim_device():
    if 'user' not in session:
        return jsonify({"status": "error", "message": "Chưa đăng nhập"}), 401
    device_id = request.get_json().get('device_id')
    if not device_id:
        return jsonify({"status": "error", "message": "Thiếu mã thiết bị"}), 400
    uid = session['user']['uid']
    db.reference(f'users/{uid}/devices/{device_id}').set(True)
    db.reference(f'devices/{device_id}/owner_uid').set(uid)
    return jsonify({"status": "success", "message": f"✅ Đã đăng ký thiết bị {device_id} thành công!"})

if __name__ == '__main__':
    print("🌾 Bù Nhìn 5.0 - AI đã thêm đầy đủ cảm biến & thời tiết vào system_instruction")
    app.run(debug=True, host='0.0.0.0', port=5000)
