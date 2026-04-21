from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# 🔐 Firebase init
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

def render_result_page(status, room=None, time=None):
    color = "#22c55e" if status == "Approved" else "#ef4444"

    return f"""
    <html>
    <head>
        <title>{status}</title>
        <style>
            body {{
                margin: 0;
                background: #0f172a;
                color: white;
                font-family: Arial, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
            }}

            .card {{
                text-align: center;
                background: #1e293b;
                padding: 40px 60px;
                border-radius: 16px;
                box-shadow: 0 0 30px rgba(0,0,0,0.4);
            }}

            .status {{
                font-size: 42px;
                font-weight: bold;
                color: {color};
                margin-bottom: 20px;
            }}

            .details {{
                font-size: 18px;
                color: #cbd5f5;
            }}
        </style>
    </head>

    <body>
        <div class="card">
            <div class="status">✅ {status}</div>
            <div class="details">
                Room: {room}<br>
                Time: {time}
            </div>
        </div>
    </body>
    </html>
    """

# 📧 Send Email Function
def send_email(req_id, room, day, time):

    sender = "classroomfinder2026@gmail.com"
    password = "tacoszzermyeeswz"

    receiver = "saadlambay1710@gmail.com"

    approve_link = f"http://127.0.0.1:5000/approve?id={req_id}"
    reject_link = f"http://127.0.0.1:5000/reject?id={req_id}"

    body = f"""
Room Booking Request

Room: {room}
Day: {day}
Time: {time}

Approve:
{approve_link}

Reject:
{reject_link}
"""

    msg = MIMEText(body)
    msg["Subject"] = "Room Booking Request"
    msg["From"] = sender
    msg["To"] = receiver

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)


# 🔍 Get free rooms (WITH EXPIRY HANDLING)
@app.route("/free-rooms")
def free_rooms():
    day = request.args.get("day").lower()
    time = request.args.get("time")

    rooms_ref = db.collection("schedule").document(day).collection("rooms")
    override_ref = db.collection("overrides").document(day).collection("rooms")

    docs = rooms_ref.stream()
    free = []

    for doc in docs:
        room = doc.id
        data = doc.to_dict()

        override_doc = override_ref.document(room).get()

        if override_doc.exists:
            override_data = override_doc.to_dict()

            # 🔥 expiry check
            if "expires_at" in override_data:
                expiry = datetime.fromisoformat(override_data["expires_at"])

                if datetime.utcnow() < expiry:
                    if time in override_data:
                        continue

        if time in data and data[time] == True:
            free.append(room)

    return jsonify({"free_rooms": sorted(free)})


# 📩 Request booking (WITH VALIDATION)
@app.route("/request-room", methods=["POST"])
def request_room():

    data = request.json
    room = data["room"]
    day = data["day"]
    time = data["time"]

    # 🔍 VALIDATION
    room_ref = db.collection("schedule").document(day).collection("rooms").document(room)
    doc = room_ref.get()

    if not doc.exists:
        return jsonify({"error": "Room does not exist"}), 400

    data_db = doc.to_dict()

    override_doc = db.collection("overrides").document(day).collection("rooms").document(room).get()

    if override_doc.exists:
        override_data = override_doc.to_dict()
        if "expires_at" in override_data:
            expiry = datetime.fromisoformat(override_data["expires_at"])
            if datetime.utcnow() < expiry and time in override_data:
                return jsonify({"error": "Room already booked"}), 400

    if time not in data_db or data_db[time] is False:
        return jsonify({"error": "Room is not free"}), 400

    # create request
    req_id = str(uuid.uuid4())

    db.collection("requests").document(req_id).set({
        "room": room,
        "day": day,
        "time": time,
        "status": "pending"
    })

    send_email(req_id, room, day, time)

    return jsonify({"request_id": req_id})


# 📊 STATUS CHECK
@app.route("/request-status")
def request_status():

    req_id = request.args.get("id")

    doc = db.collection("requests").document(req_id).get()

    if not doc.exists:
        return jsonify({"status": "not_found"})

    return jsonify({"status": doc.to_dict()["status"]})


# ✅ APPROVE (WITH EXPIRY)
@app.route("/approve")
def approve():

    req_id = request.args.get("id")

    doc_ref = db.collection("requests").document(req_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "❌ Request not found"

    data = doc.to_dict()

    doc_ref.update({"status": "approved"})

    expiry_time = datetime.utcnow() + timedelta(hours=1)

    db.collection("overrides") \
      .document(data["day"]) \
      .collection("rooms") \
      .document(data["room"]) \
      .set({
          data["time"]: True,
          "expires_at": expiry_time.isoformat()
      }, merge=True)

    return render_result_page("Approved", data["room"], data["time"])


# ❌ REJECT
@app.route("/reject")
def reject():

    req_id = request.args.get("id")

    db.collection("requests").document(req_id).update({
        "status": "rejected"
    })

    return render_result_page("Rejected")

# 🏢 GET ALL ROOMS (for floors layout)
@app.route("/all-rooms")
def get_all_rooms():
    rooms = []

    # 🔥 use a known existing day
    rooms_ref = db.collection("schedule") \
                  .document("monday") \
                  .collection("rooms") \
                  .stream()

    for room_doc in rooms_ref:
        rooms.append(room_doc.id)

    return jsonify({"rooms": sorted(rooms)})

if __name__ == "__main__":
    app.run(debug=True)