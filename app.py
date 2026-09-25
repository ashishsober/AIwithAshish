import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, jsonify, request, send_from_directory
from src.qwen_client import ask_qwen

app = Flask(__name__, static_folder=str(ROOT_DIR / "frontend" / "dist"), static_url_path="")


@app.route("/api/chat", methods=["GET", "POST"])
def chat_api():
    if request.method == "GET":
        prompt = request.args.get("prompt", "").strip()
    else:
        payload = request.get_json(silent=True) or {}
        prompt = (payload.get("prompt") or payload.get("context") or "").strip()

    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    try:
        response = ask_qwen(prompt)
        return jsonify({"response": response})
    except Exception as exc:  # pragma: no cover - runtime safety guard
        return jsonify({"error": str(exc)}), 500


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    dist_dir = ROOT_DIR / "frontend" / "dist"

    if path and (dist_dir / path).exists():
        return send_from_directory(str(dist_dir), path)

    return send_from_directory(str(dist_dir), "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
