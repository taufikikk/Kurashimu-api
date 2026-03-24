"""
暮らシム — Backend API
Flask + Neon PostgreSQL
"""
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone

# ── App Setup ───────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {"sslmode": "require"} if DATABASE_URL else {},
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ── Models ──────────────────────────────────────────────────────
class Scene(db.Model):
    __tablename__ = "scenes"

    id = db.Column(db.Integer, primary_key=True)
    scene_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    title_reading = db.Column(db.String(200))
    title_id = db.Column(db.String(200))
    description = db.Column(db.Text)
    level = db.Column(db.String(10))  # N5, N4, N3, N2, N1
    phase = db.Column(db.Integer)
    tone = db.Column(db.String(50))
    tier = db.Column(db.Integer, default=1, index=True)  # content tier
    situation_tags = db.Column(JSONB, default=[])
    data = db.Column(JSONB, nullable=False)  # Full scene JSON
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_summary(self):
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "title_reading": self.title_reading,
            "title_id": self.title_id,
            "description": self.description,
            "level": self.level,
            "phase": self.phase,
            "tone": self.tone,
            "tier": self.tier,
            "situation_tags": self.situation_tags or [],
            "node_count": len(self.data.get("nodes", [])) if self.data else 0,
            "choice_count": len([n for n in self.data.get("nodes", []) if n.get("type") == "choice"]) if self.data else 0,
        }

    def to_full(self):
        return self.data


class PlayerState(db.Model):
    __tablename__ = "player_states"

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    player_name = db.Column(db.String(100))
    speech_style = db.Column(db.String(20), default="masculine")
    progress = db.Column(JSONB, default={})
    flags = db.Column(JSONB, default={})
    learning = db.Column(JSONB, default={})
    settings = db.Column(JSONB, default={})
    saves = db.Column(JSONB, default={})
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "speech_style": self.speech_style,
            "progress": self.progress or {},
            "flags": self.flags or {},
            "learning": self.learning or {},
            "settings": self.settings or {},
            "saves": self.saves or {},
        }


# ── Access Control ──────────────────────────────────────────────

def get_max_tier():
    """Check request header for elevated access. Default tier 1.
    Returns (max_tier, error_response). If key is provided but wrong, returns 401.
    """
    key = request.headers.get("X-Access-Key", "")
    t2_key = os.environ.get("ACCESS_KEY_T2", "")
    if key:
        if t2_key and key == t2_key:
            return 2, None
        return None, (jsonify({"error": "Invalid access key"}), 401)
    return 1, None


# ── Scene Endpoints ─────────────────────────────────────────────

@app.route("/api/scenes", methods=["GET"])
def list_scenes():
    """List all scenes with optional filters. Tier-gated."""
    max_tier, err = get_max_tier()
    if err:
        return err
    level = request.args.get("level")
    phase = request.args.get("phase", type=int)
    tag = request.args.get("tag")

    query = Scene.query.filter(Scene.tier <= max_tier).order_by(Scene.phase, Scene.scene_id)

    if level:
        query = query.filter(Scene.level == level)
    if phase is not None:
        query = query.filter(Scene.phase == phase)
    if tag:
        query = query.filter(Scene.situation_tags.contains([tag]))

    scenes = query.all()
    return jsonify({
        "scenes": [s.to_summary() for s in scenes],
        "total": len(scenes),
    })


@app.route("/api/scenes/<scene_id>", methods=["GET"])
def get_scene(scene_id):
    """Get full scene data by scene_id. Tier-gated."""
    max_tier, err = get_max_tier()
    if err:
        return err
    scene = Scene.query.filter_by(scene_id=scene_id).first()
    if not scene or scene.tier > max_tier:
        return jsonify({"error": "Scene not found"}), 404
    return jsonify(scene.to_full())


@app.route("/api/scenes", methods=["POST"])
def create_scene():
    """Upload a new scene or update existing."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON provided"}), 400

    scene_id = data.get("scene_id")
    if not scene_id:
        return jsonify({"error": "Missing scene_id"}), 400
    if not data.get("nodes"):
        return jsonify({"error": "Missing nodes"}), 400

    existing = Scene.query.filter_by(scene_id=scene_id).first()
    if existing:
        existing.title = data.get("title", existing.title)
        existing.title_reading = data.get("title_reading")
        existing.title_id = data.get("title_id")
        existing.description = data.get("description")
        existing.level = data.get("level")
        existing.phase = data.get("phase")
        existing.tone = data.get("tone")
        existing.tier = data.get("tier", 1)
        existing.situation_tags = data.get("situation_tags", [])
        existing.data = data
        db.session.commit()
        return jsonify({"status": "updated", "scene_id": scene_id})
    else:
        scene = Scene(
            scene_id=scene_id,
            title=data.get("title", scene_id),
            title_reading=data.get("title_reading"),
            title_id=data.get("title_id"),
            description=data.get("description"),
            level=data.get("level"),
            phase=data.get("phase"),
            tone=data.get("tone"),
            tier=data.get("tier", 1),
            situation_tags=data.get("situation_tags", []),
            data=data,
        )
        db.session.add(scene)
        db.session.commit()
        return jsonify({"status": "created", "scene_id": scene_id}), 201


@app.route("/api/scenes/<scene_id>", methods=["DELETE"])
def delete_scene(scene_id):
    """Delete a scene."""
    scene = Scene.query.filter_by(scene_id=scene_id).first()
    if not scene:
        return jsonify({"error": "Scene not found"}), 404
    db.session.delete(scene)
    db.session.commit()
    return jsonify({"status": "deleted", "scene_id": scene_id})


# ── Batch Upload ────────────────────────────────────────────────

@app.route("/api/scenes/batch", methods=["POST"])
def batch_upload():
    """Upload multiple scenes at once."""
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"error": "Expected JSON array of scenes"}), 400

    results = []
    for scene_data in data:
        scene_id = scene_data.get("scene_id")
        if not scene_id or not scene_data.get("nodes"):
            results.append({"scene_id": scene_id, "status": "skipped", "reason": "missing scene_id or nodes"})
            continue

        existing = Scene.query.filter_by(scene_id=scene_id).first()
        if existing:
            existing.title = scene_data.get("title", existing.title)
            existing.title_reading = scene_data.get("title_reading")
            existing.title_id = scene_data.get("title_id")
            existing.description = scene_data.get("description")
            existing.level = scene_data.get("level")
            existing.phase = scene_data.get("phase")
            existing.tone = scene_data.get("tone")
            existing.tier = scene_data.get("tier", 1)
            existing.situation_tags = scene_data.get("situation_tags", [])
            existing.data = scene_data
            results.append({"scene_id": scene_id, "status": "updated"})
        else:
            scene = Scene(
                scene_id=scene_id,
                title=scene_data.get("title", scene_id),
                title_reading=scene_data.get("title_reading"),
                title_id=scene_data.get("title_id"),
                description=scene_data.get("description"),
                level=scene_data.get("level"),
                phase=scene_data.get("phase"),
                tone=scene_data.get("tone"),
                tier=scene_data.get("tier", 1),
                situation_tags=scene_data.get("situation_tags", []),
                data=scene_data,
            )
            db.session.add(scene)
            results.append({"scene_id": scene_id, "status": "created"})

    db.session.commit()
    return jsonify({"results": results, "total": len(results)})


# ── Player State Endpoints ──────────────────────────────────────

@app.route("/api/player/<player_id>", methods=["GET"])
def get_player(player_id):
    """Get player state."""
    player = PlayerState.query.filter_by(player_id=player_id).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404
    return jsonify(player.to_dict())


@app.route("/api/player/<player_id>", methods=["PUT"])
def update_player(player_id):
    """Create or update player state."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON provided"}), 400

    player = PlayerState.query.filter_by(player_id=player_id).first()
    if not player:
        player = PlayerState(player_id=player_id)
        db.session.add(player)

    if "player_name" in data:
        player.player_name = data["player_name"]
    if "speech_style" in data:
        player.speech_style = data["speech_style"]
    if "progress" in data:
        player.progress = data["progress"]
    if "flags" in data:
        player.flags = data["flags"]
    if "learning" in data:
        player.learning = data["learning"]
    if "settings" in data:
        player.settings = data["settings"]
    if "saves" in data:
        player.saves = data["saves"]

    db.session.commit()
    return jsonify({"status": "saved", "player_id": player_id})


@app.route("/api/player/<player_id>/scene/<scene_id>", methods=["PUT"])
def update_scene_progress(player_id, scene_id):
    """Update progress for a specific scene (partial update)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON provided"}), 400

    player = PlayerState.query.filter_by(player_id=player_id).first()
    if not player:
        player = PlayerState(player_id=player_id, progress={})
        db.session.add(player)

    progress = player.progress or {}
    if "scenes_completed" not in progress:
        progress["scenes_completed"] = {}

    progress["scenes_completed"][scene_id] = data
    player.progress = progress
    # Force SQLAlchemy to detect JSONB change
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(player, "progress")

    db.session.commit()
    return jsonify({"status": "updated", "scene_id": scene_id})


# ── Health ──────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    """Health check."""
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "db": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "db": str(e)}), 500


# ── Init DB ─────────────────────────────────────────────────────

@app.route("/api/init", methods=["POST"])
def init_db():
    """Create tables. Call once after deploy."""
    db.create_all()
    return jsonify({"status": "tables created"})


# ── Seed ────────────────────────────────────────────────────────

@app.route("/api/seed", methods=["POST"])
def seed_scenes():
    """Seed with golden examples from request body."""
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"error": "Expected JSON array of scenes"}), 400

    count = 0
    for scene_data in data:
        scene_id = scene_data.get("scene_id")
        if not scene_id:
            continue
        existing = Scene.query.filter_by(scene_id=scene_id).first()
        if not existing:
            scene = Scene(
                scene_id=scene_id,
                title=scene_data.get("title", scene_id),
                title_reading=scene_data.get("title_reading"),
                title_id=scene_data.get("title_id"),
                description=scene_data.get("description"),
                level=scene_data.get("level"),
                phase=scene_data.get("phase"),
                tone=scene_data.get("tone"),
                tier=scene_data.get("tier", 1),
                situation_tags=scene_data.get("situation_tags", []),
                data=scene_data,
            )
            db.session.add(scene)
            count += 1

    db.session.commit()
    return jsonify({"status": "seeded", "new_scenes": count})


# ── Run ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
