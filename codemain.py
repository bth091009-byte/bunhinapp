from flask import Flask, render_template, request, jsonify, redirect, session
import firebase_admin
from firebase_admin import credentials, db
import requests
import google.generativeai as genai
from datetime import datetime
import base64, io, os, traceback
import json

app = Flask(__name__, template_folder='.')
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
GEMINI_API_KEY_CHAT = os.environ.get("GEMINI_API_KEY_CHAT")
GEMINI_API_KEY_DISEASE = os.environ.get("GEMINI_API_KEY_DISEASE")
GEMINI_API_KEY_LEARNING = os.environ.get("GEMINI_API_KEY_LEARNING")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
DEFAULT_LAT = 10.113796828786487
DEFAULT_LNG = 106.26956157081204

# if not GEMINI_API_KEY or not WEATHER_API_KEY:
#     raise ValueError("❌ Missing GEMINI_API_KEY or WEATHER_API_KEY")

#10.113796828786487, 106.26956157081204

# ================== Khởi tạo Gemini (Chat — dùng mặc định) ==================
genai.configure(api_key=GEMINI_API_KEY_CHAT)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
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

    QUAN TRỌNG - ĐỊNH DẠNG TRẢ LỜI:
    Tuyệt đối không dùng bất kỳ ký hiệu markdown nào. Không dùng dấu * hay ** để in đậm hoặc in nghiêng.
    Không dùng dấu gạch đầu dòng (-), không đánh số thứ tự (1. 2. 3.), không dùng ký tự # cho tiêu đề.
    Không dùng backtick hay code block. Viết văn xuôi tự nhiên như người nói chuyện bình thường.
    Nếu cần liệt kê, hãy viết thành câu như: "Thứ nhất là..., thứ hai là..., cuối cùng là...".
    """
)

# ================== HELPER ==================
def get_current_device():
    return session.get('current_device', 'BN5001')

# ================== ROUTES ==================
@app.route('/')
def home():
    user = session.get('user')
    current_device = get_current_device()
    return render_template('index.html', 
                         user=user, 
                         WEATHER_API_KEY=WEATHER_API_KEY,
                         DEFAULT_LAT=DEFAULT_LAT, 
                         DEFAULT_LNG=DEFAULT_LNG,
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
        w = requests.get(
            f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={WEATHER_API_KEY}&units=metric&lang=vi",
            timeout=8).json()
        weather_str = f"{w['weather'][0]['description']}, {w['main']['temp']}°C, độ ẩm {w['main']['humidity']}%"
    except Exception:
        pass

    current_time = datetime.now().strftime("%H:%M ngày %d/%m/%Y")
    prompt = f"""Thời gian hiện tại: {current_time}
Dữ liệu ruộng:
- Nhiệt độ: {sensors.get('temp', '---')}°C
- Độ ẩm KK: {sensors.get('hum', '---')}% 
- Độ ẩm đất: {sensors.get('soil', '---')}% 
- Ánh sáng: {sensors.get('lux', '---')} lux
- Mưa: {'Có mưa' if sensors.get('rain', 3000) < 2000 else 'Không mưa'}
- Thời tiết: {weather_str}

Câu hỏi: "{query}"

Trả lời bằng văn xuôi tự nhiên, gần gũi như nói chuyện với bà con, không dùng bất kỳ ký tự markdown nào."""

    try:
        genai.configure(api_key=GEMINI_API_KEY_CHAT)
        chat = model.start_chat(history=[])
        response = chat.send_message(prompt)
        advice = response.text.strip()
    except Exception as e:
        print("Gemini Error:", e)
        advice = "Xin lỗi bà con, AI đang bận do quota. Vui lòng thử lại sau 30 giây nhé!"

    return jsonify({"advice": advice})


@app.route('/analyze_disease', methods=['POST'])
def analyze_disease():
    data = request.get_json() or {}
    image_b64 = data.get('image', '')

    if not image_b64:
        return jsonify({"error": "Không có ảnh", "disease_count": 0, "detections": [], "ai_advice": ""}), 400

    if ',' in image_b64:
        header, image_b64_clean = image_b64.split(',', 1)
        media_type = header.split(':')[1].split(';')[0] if ':' in header else 'image/jpeg'
    else:
        image_b64_clean = image_b64
        media_type = 'image/jpeg'

    detections = []
    ai_advice = ""

    try:
        genai.configure(api_key=GEMINI_API_KEY_DISEASE)

        prompt_text = """Bà con gửi ảnh cây lúa để kiểm tra bệnh. Hãy phân tích ảnh và trả về JSON theo đúng định dạng sau (chỉ JSON, không giải thích thêm):

{
  "detections": [
    {"name": "Tên bệnh tiếng Việt", "confidence": 0.85}
  ],
  "ai_advice": "Lời khuyên chi tiết cho bà con bằng văn xuôi tự nhiên, không markdown"
}

Các bệnh lúa phổ biến cần nhận biết: Đạo ôn, Khô vằn, Lem lép hạt, Bạc lá, Vàng lá, Sâu cuốn lá, Rầy nâu, Cây khỏe mạnh.
Nếu cây khỏe, detections trả về [{"name": "Cây khỏe mạnh", "confidence": 0.95}].
confidence là số từ 0.0 đến 1.0 thể hiện mức độ chắc chắn.
Chỉ trả về JSON thuần túy, không có markdown, không có backtick."""

        vision = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction="Bạn là chuyên gia bệnh học cây lúa vùng ĐBSCL Việt Nam. Chỉ trả về JSON đúng định dạng yêu cầu, không thêm bất kỳ text nào khác."
        )

        image_part = {"inline_data": {"mime_type": media_type, "data": image_b64_clean}}
        response = vision.generate_content([prompt_text, image_part])
        raw = response.text.strip().replace("```json", "").replace("```", "").strip()

        import json
        parsed = json.loads(raw)
        detections = parsed.get("detections", [])
        ai_advice  = parsed.get("ai_advice", "")

    except Exception as e:
        print("Gemini Vision Rice Error:", traceback.format_exc())
        ai_advice = "Không thể phân tích ảnh lúc này. Vui lòng thử lại sau."

    return jsonify({
        "disease_count": len([d for d in detections if d.get("name") != "Cây khỏe mạnh"]),
        "detections": detections,
        "ai_advice": ai_advice
    })


@app.route('/analyze_coconut_disease', methods=['POST'])
def analyze_coconut_disease():
    data = request.get_json() or {}
    image_b64 = data.get('image', '')

    if not image_b64:
        return jsonify({"error": "Không có ảnh", "disease_count": 0, "detections": [], "ai_advice": ""}), 400

    if ',' in image_b64:
        header, image_b64_clean = image_b64.split(',', 1)
        media_type = header.split(':')[1].split(';')[0] if ':' in header else 'image/jpeg'
    else:
        image_b64_clean = image_b64
        media_type = 'image/jpeg'

    detections = []
    ai_advice = ""

    try:
        genai.configure(api_key=GEMINI_API_KEY_DISEASE)

        prompt_text = """Bà con gửi ảnh cây dừa để kiểm tra bệnh. Hãy phân tích ảnh và trả về JSON theo đúng định dạng sau (chỉ JSON, không giải thích thêm):

{
  "detections": [
    {"name": "Tên bệnh tiếng Việt", "confidence": 0.85}
  ],
  "ai_advice": "Lời khuyên chi tiết cho bà con bằng văn xuôi tự nhiên, không markdown"
}

Các bệnh dừa cần nhận biết: Bệnh đốm lá, Bệnh thối rễ, Bệnh vàng lá, Bọ cánh cứng (Bọ dừa), Bệnh thối đọt, Cây khỏe mạnh.
Nếu cây khỏe, detections trả về [{"name": "Cây khỏe mạnh", "confidence": 0.95}].
confidence là số từ 0.0 đến 1.0 thể hiện mức độ chắc chắn.
Chỉ trả về JSON thuần túy, không có markdown, không có backtick."""

        vision = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction="Bạn là chuyên gia bệnh học cây dừa vùng ĐBSCL Việt Nam. Chỉ trả về JSON đúng định dạng yêu cầu, không thêm bất kỳ text nào khác."
        )

        image_part = {"inline_data": {"mime_type": media_type, "data": image_b64_clean}}
        response = vision.generate_content([prompt_text, image_part])
        raw = response.text.strip().replace("```json", "").replace("```", "").strip()

        import json
        parsed = json.loads(raw)
        detections = parsed.get("detections", [])
        ai_advice  = parsed.get("ai_advice", "")

    except Exception as e:
        print("Gemini Vision Coconut Error:", traceback.format_exc())
        ai_advice = "Không thể phân tích ảnh lúc này. Vui lòng thử lại sau."

    return jsonify({
        "disease_count": len([d for d in detections if d.get("name") != "Cây khỏe mạnh"]),
        "detections": detections,
        "ai_advice": ai_advice
    })


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
    if 'user' not in session:
        return jsonify({"status": "error", "devices": [], "current": "BN5001"}), 401
    uid = session['user']['uid']
    try:
        raw = db.reference(f'users/{uid}/devices').get() or {}
        device_ids = list(raw.keys()) if isinstance(raw, dict) else []
    except Exception:
        device_ids = []
    if not device_ids:
        device_ids = ['BN5001']
    current = get_current_device()
    devices_info = []
    for did in device_ids:
        name = db.reference(f'devices/{did}/name').get() or did
        devices_info.append({"id": did, "name": name})
    return jsonify({"status": "ok", "devices": devices_info, "current": current})


@app.route('/select_device', methods=['POST'])
def select_device():
    if 'user' not in session:
        return jsonify({"status": "error", "message": "Chưa đăng nhập"}), 401
    data = request.get_json() or {}
    device_id = data.get('device_id', 'BN5001').strip()
    session['current_device'] = device_id
    try:
        db.reference(f'devices/{device_id}/last_seen').set(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
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
    return jsonify({"status": "success", "message": f"Đã đăng ký thiết bị {device_id} thành công!"})


# ================== LEARNING HUB ROUTES ==================

LEARNING_FORMAT_RULES = """
QUAN TRỌNG - ĐỊNH DẠNG TRẢ LỜI:
Tuyệt đối không dùng bất kỳ ký hiệu markdown nào. Không dùng dấu * hay ** để in đậm hoặc in nghiêng.
Không dùng dấu gạch đầu dòng (-), không đánh số thứ tự (1. 2. 3.), không dùng ký tự # cho tiêu đề.
Viết văn xuôi tự nhiên như người nói chuyện bình thường. Dùng emoji phù hợp để làm sinh động.
"""

@app.route('/learning_chat', methods=['POST'])
def learning_chat():
    if 'user' not in session:
        return jsonify({"reply": "Vui lòng đăng nhập để sử dụng tính năng này."}), 401

    data = request.get_json() or {}
    system_prompt = data.get('system_prompt', '')
    messages = data.get('messages', [])
    sensor_context = data.get('sensor_context', '')

    if not messages:
        return jsonify({"reply": "Không có tin nhắn."}), 400

    # Lấy dữ liệu cảm biến realtime từ Firebase
    current_device = get_current_device()
    try:
        sensors = db.reference(f'/devices/{current_device}/sensors').get() or {}
        server_sensor = (
            f"Dữ liệu cảm biến ruộng hiện tại: "
            f"Nhiệt độ {sensors.get('temp','---')}°C, "
            f"Độ ẩm KK {sensors.get('hum','---')}%, "
            f"Ánh sáng {sensors.get('lux','---')} lux, "
            f"Độ ẩm đất {sensors.get('soil','---')}%."
        )
    except Exception:
        server_sensor = sensor_context

    full_system = system_prompt + "\n\n" + LEARNING_FORMAT_RULES

    # Build Gemini history từ danh sách messages (trừ message cuối cùng)
    gemini_history = []
    for msg in messages[:-1]:
        role = "user" if msg['role'] == 'user' else "model"
        gemini_history.append({"role": role, "parts": [msg['content']]})

    last_msg = messages[-1]
    user_text = (server_sensor + "\n\n" + last_msg['content']) if len(messages) == 1 else last_msg['content']

    try:
        genai.configure(api_key=GEMINI_API_KEY_LEARNING)
        learn_model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction=full_system
        )
        chat_session = learn_model.start_chat(history=gemini_history)
        response = chat_session.send_message(user_text)
        reply = response.text.strip()
    except Exception as e:
        print("Learning Chat Error:", e)
        reply = "Xin lỗi, AI đang bận. Vui lòng thử lại sau 30 giây nhé! 🙏"

    return jsonify({"reply": reply})


@app.route('/learning_report', methods=['POST'])
def learning_report():
    if 'user' not in session:
        return jsonify({"report": "Vui lòng đăng nhập."}), 401

    data = request.get_json() or {}
    prompt_text = data.get('prompt', '')
    if not prompt_text:
        return jsonify({"report": "Không có dữ liệu."}), 400

    # Gắn dữ liệu cảm biến từ server vào báo cáo
    current_device = get_current_device()
    try:
        sensors = db.reference(f'/devices/{current_device}/sensors').get() or {}
        sensor_str = (
            f"Dữ liệu cảm biến hiện tại: nhiệt độ {sensors.get('temp','---')}°C, "
            f"độ ẩm KK {sensors.get('hum','---')}%, "
            f"ánh sáng {sensors.get('lux','---')} lux, "
            f"độ ẩm đất {sensors.get('soil','---')}%."
        )
        prompt_text = sensor_str + "\n\n" + prompt_text
    except Exception:
        pass

    full_system = (
        "Bạn là Bù Nhìn 5.0 - AI gia sư nông nghiệp thông minh. "
        "Hãy viết báo cáo học tập cá nhân hóa cho học sinh: thân thiện, khuyến khích, thực tế, khoảng 200 từ.\n\n"
        + LEARNING_FORMAT_RULES
    )

    try:
        genai.configure(api_key=GEMINI_API_KEY_LEARNING)
        report_model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction=full_system
        )
        chat_session = report_model.start_chat(history=[])
        response = chat_session.send_message(prompt_text)
        report = response.text.strip()
    except Exception as e:
        print("Learning Report Error:", e)
        report = "Không thể tạo báo cáo lúc này. Vui lòng thử lại sau. 🙏"

    return jsonify({"report": report})


if __name__ == '__main__':
    print("🌾 Bù Nhìn 5.0 - AI đã thêm đầy đủ cảm biến & thời tiết vào system_instruction")
    app.run(debug=True, host='0.0.0.0', port=5000)
