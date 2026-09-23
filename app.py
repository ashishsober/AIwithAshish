import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, render_template_string, request
from src.qwen_client import ask_qwen

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Qwen Chat UI</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #111827;
      color: #f3f4f6;
      margin: 0;
      padding: 30px;
    }
    .container {
      max-width: 900px;
      margin: 0 auto;
      background: #1f2937;
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }
    h1 {
      margin-top: 0;
    }
    textarea {
      width: 100%;
      min-height: 200px;
      border-radius: 10px;
      border: 1px solid #374151;
      padding: 14px;
      font-size: 16px;
      background: #0f172a;
      color: white;
      resize: vertical;
      box-sizing: border-box;
    }
    button {
      margin-top: 14px;
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 8px;
      padding: 12px 20px;
      font-size: 16px;
      cursor: pointer;
    }
    .response {
      margin-top: 25px;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 16px;
      white-space: pre-wrap;
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Qwen Context Prompt UI</h1>
    <form method="post">
      <label for="context">Enter context or question for Qwen</label>
      <textarea name="context" id="context" placeholder="Paste your context here...">{{ context }}</textarea>
      <button type="submit">Send to Qwen</button>
    </form>

    {% if response %}
    <div class="response">
      <strong>Qwen response:</strong>
      {{ response }}
    </div>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    context = ""
    response = ""

    if request.method == "POST":
        context = request.form.get("context", "")
        if context.strip():
            response = ask_qwen(context)

    return render_template_string(HTML, context=context, response=response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
