import os
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
UPLOAD_DIR = "cloud_storage"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/")
def home():
    return "Monika Cloud Storage Server is running!"

@app.route("/upload/<filename>", methods=["POST"])
def upload_file(filename):
    data = request.data
    if not data:
        return "No data", 400

    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(data)

    return "Upload successful", 200

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return "File not found", 404

    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/list", methods=["GET"])
def list_files():
    files = os.listdir(UPLOAD_DIR)
    return jsonify(files)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)