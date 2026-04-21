"""
PhCharts — servidor Flask
  pip install flask
  python app.py
"""

import os, json, zipfile, shutil, tempfile, uuid, time
from flask import (Flask, request, jsonify, send_from_directory,
                   send_file, abort)

app = Flask(__name__, static_folder="static", static_url_path="")

UPLOAD_DIR  = "uploads"
COVER_DIR   = "static/covers"
DB_FILE     = "charts.json"
ALLOWED_EXT = {".phchart"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(COVER_DIR,  exist_ok=True)

# ── helpers de dificuldade ────────────────────────────────────────────
def diff_label(n):
    try: n = float(n)
    except: return "?"
    if n <= 10:  return "Fácil"
    if n <= 14:  return "Normal"
    if n <= 16:  return "Difícil"
    return "Extremo"

def diff_color(n):
    try: n = float(n)
    except: return "gray"
    if n <= 10:  return "easy"
    if n <= 14:  return "normal"
    if n <= 16:  return "hard"
    return "extreme"

# ── banco de dados simples (JSON) ──────────────────────────────────────
def load_db():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE) as f: return json.load(f)
    except: return []

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def find_chart(cid):
    return next((c for c in load_db() if c["id"] == cid), None)

# ── extrair metadados do .phchart ─────────────────────────────────────
def extract_meta(phchart_path):
    meta = {}
    tmp = tempfile.mkdtemp(prefix="ph_")
    try:
        with zipfile.ZipFile(phchart_path, "r") as zf:
            zf.extractall(tmp)
        with open(os.path.join(tmp, "chart.json")) as f:
            data = json.load(f)
        meta["chart_name"]  = data.get("chart_name", "Sem título")
        meta["columns"]     = data.get("columns", 4)
        meta["note_count"]  = len(data.get("notes", []))
        meta["difficulty"]  = str(data.get("difficulty", "")).strip()
        # capa embutida no zip?
        cover_arc = data.get("cover_arc")
        if cover_arc:
            src = os.path.join(tmp, cover_arc)
            if os.path.exists(src):
                ext = os.path.splitext(cover_arc)[1]
                cover_name = str(uuid.uuid4()) + ext
                shutil.copy2(src, os.path.join(COVER_DIR, cover_name))
                meta["_embedded_cover"] = cover_name
    except Exception as e:
        print(f"extract_meta error: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return meta

# ══════════════════════════════════════════════════════════════════════
#  ROTAS
# ══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── listar charts ─────────────────────────────────────────────────────
@app.route("/api/charts")
def api_charts():
    db = load_db()
    sort  = request.args.get("sort", "recent")
    diff  = request.args.get("diff", "")
    query = request.args.get("q", "").lower()

    # filtro
    if diff:
        db = [c for c in db if diff_color(c.get("difficulty","")) == diff]
    if query:
        db = [c for c in db if query in c.get("chart_name","").lower()
              or query in c.get("author","").lower()]

    # ordenação
    if sort == "rating":
        db = sorted(db, key=lambda c: c.get("rating_avg", 0), reverse=True)
    elif sort == "downloads":
        db = sorted(db, key=lambda c: c.get("downloads", 0), reverse=True)
    else:
        db = sorted(db, key=lambda c: c.get("uploaded_at", 0), reverse=True)

    # formatar para resposta
    out = []
    for c in db:
        out.append({
            "id":          c["id"],
            "chart_name":  c.get("chart_name", "Sem título"),
            "author":      c.get("author", "anônimo"),
            "difficulty":  c.get("difficulty", ""),
            "diff_label":  diff_label(c.get("difficulty", "")),
            "diff_color":  diff_color(c.get("difficulty", "")),
            "columns":     c.get("columns", 4),
            "note_count":  c.get("note_count", 0),
            "downloads":   c.get("downloads", 0),
            "rating_avg":  round(c.get("rating_avg", 0), 1),
            "rating_count":c.get("rating_count", 0),
            "cover":       c.get("cover"),
            "uploaded_at": c.get("uploaded_at", 0),
        })
    return jsonify(out)

# ── upload ────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def api_upload():
    file   = request.files.get("phchart")
    author = request.form.get("author", "anônimo").strip()[:40]
    cover_file = request.files.get("cover")

    if not file:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    if not file.filename.endswith(".phchart"):
        return jsonify({"error": "Apenas arquivos .phchart"}), 400

    cid      = str(uuid.uuid4())[:8]
    filename = cid + ".phchart"
    dest     = os.path.join(UPLOAD_DIR, filename)
    file.save(dest)

    meta = extract_meta(dest)
    cover_name = meta.pop("_embedded_cover", None)

    # capa enviada manualmente sobrepõe a embutida
    if cover_file and cover_file.filename:
        ext = os.path.splitext(cover_file.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            cover_name = cid + ext
            cover_file.save(os.path.join(COVER_DIR, cover_name))

    db = load_db()
    db.append({
        "id":           cid,
        "filename":     filename,
        "chart_name":   meta.get("chart_name", "Sem título"),
        "author":       author,
        "difficulty":   meta.get("difficulty", ""),
        "columns":      meta.get("columns", 4),
        "note_count":   meta.get("note_count", 0),
        "cover":        cover_name,
        "downloads":    0,
        "ratings":      [],
        "rating_avg":   0,
        "rating_count": 0,
        "uploaded_at":  int(time.time()),
    })
    save_db(db)
    return jsonify({"ok": True, "id": cid})

# ── download ──────────────────────────────────────────────────────────
@app.route("/api/download/<cid>")
def api_download(cid):
    chart = find_chart(cid)
    if not chart: abort(404)
    path = os.path.join(UPLOAD_DIR, chart["filename"])
    if not os.path.exists(path): abort(404)
    # incrementa contador
    db = load_db()
    for c in db:
        if c["id"] == cid:
            c["downloads"] = c.get("downloads", 0) + 1
            break
    save_db(db)
    return send_file(path, as_attachment=True,
                     download_name=chart["chart_name"] + ".phchart")

# ── rating ────────────────────────────────────────────────────────────
@app.route("/api/rate/<cid>", methods=["POST"])
def api_rate(cid):
    body = request.get_json(silent=True) or {}
    stars = int(body.get("stars", 0))
    if stars < 1 or stars > 5:
        return jsonify({"error": "estrelas entre 1 e 5"}), 400
    # identificação anônima por IP
    ip = request.remote_addr
    db = load_db()
    for c in db:
        if c["id"] == cid:
            ratings = c.setdefault("ratings", [])
            # remove voto anterior deste IP
            ratings = [r for r in ratings if r.get("ip") != ip]
            ratings.append({"ip": ip, "stars": stars})
            c["ratings"]      = ratings
            c["rating_avg"]   = round(sum(r["stars"] for r in ratings) / len(ratings), 2)
            c["rating_count"] = len(ratings)
            save_db(db)
            return jsonify({"ok": True, "avg": c["rating_avg"], "count": c["rating_count"]})
    abort(404)

# ── capa ──────────────────────────────────────────────────────────────
@app.route("/covers/<filename>")
def serve_cover(filename):
    return send_from_directory(COVER_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
