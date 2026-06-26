# relay_server.py - runs on a laptop or VPS, NOT on the Pico.
#
# Holds your Anthropic API key and turns device state into hardware actions,
# so the key never lives in firmware you flash over the air.
#
#   pip install flask anthropic
#   export ANTHROPIC_API_KEY=sk-ant-...
#   python relay_server.py

import json
from flask import Flask, request, jsonify
import anthropic

client = anthropic.Anthropic()      # reads ANTHROPIC_API_KEY from the environment
app = Flask(__name__)

SYSTEM = (
    "You control a Raspberry Pi Pico W with one LED and one button. "
    "You receive the device state as JSON and decide what the hardware does. "
    "Respond with ONLY a JSON object, no prose and no code fences. "
    'Valid shapes: {"led": "on"} or {"led": "off"}. '
    "Rule: turn the LED on while the button is pressed, off otherwise."
)


@app.post("/decide")
def decide():
    state = request.get_json(force=True).get("state", {})
    msg = client.messages.create(
        model="claude-haiku-4-5",   # fast + cheap: right choice for a control loop
        max_tokens=128,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(state)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        action = json.loads(text)
    except ValueError:
        action = {"led": "off"}     # safe default if the model returns non-JSON
    return jsonify(action)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
