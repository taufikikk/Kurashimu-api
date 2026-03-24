"""
Seed script — upload scene JSON files to 暮らシム API.

Usage:
  python seed.py                          # seed all .json files in current dir
  python seed.py scene1.json scene2.json  # seed specific files
  
Set API_URL env var if not localhost:
  API_URL=https://your-app.railway.app python seed.py
"""
import sys
import os
import json
import urllib.request
import urllib.error

API_URL = os.environ.get("API_URL", "http://localhost:5000")


def upload_scene(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    scene_id = data.get("scene_id", "unknown")
    url = f"{API_URL}/api/scenes"

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            status = result.get("status", "?")
            print(f"  ✓ {scene_id} — {status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  ✗ {scene_id} — HTTP {e.code}: {body}")
    except Exception as e:
        print(f"  ✗ {scene_id} — Error: {e}")


def main():
    # Init tables first
    print(f"API: {API_URL}")
    try:
        req = urllib.request.Request(f"{API_URL}/api/init", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=b"{}")
        with urllib.request.urlopen(req) as resp:
            print(f"DB init: {resp.read().decode()}")
    except Exception as e:
        print(f"DB init skipped: {e}")

    # Determine files to upload
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted([f for f in os.listdir(".") if f.endswith(".json") and not f.startswith(".")])

    if not files:
        print("No .json files found.")
        return

    print(f"\nUploading {len(files)} scene(s)...")
    for f in files:
        upload_scene(f)
    print("\nDone!")


if __name__ == "__main__":
    main()
