"""
PhCharts — servidor Flask com Supabase + Auth
"""
import os, json, zipfile, shutil, tempfile, uuid, time
from flask import Flask, request, jsonify, send_from_directory, redirect, abort
from supabase import create_client, Client

app = Flask(__name__, static_folder="static", static_url_path="")

SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_KEY"]   # service_role
SUPABASE_ANON = os.environ.get("SUPABASE_ANON", "")
sb: Client    = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_CHARTS = "charts"
BUCKET_COVERS = "covers"

# ── helpers ───────────────────────────────────────────────────────
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

def public_url(bucket, filename):
    if not filename: return None
    return sb.storage.from_(bucket).get_public_url(filename)

def find_chart(cid):
    res = sb.table("charts").select("*").eq("id", cid).execute()
    return res.data[0] if res.data else None

def extract_meta(phchart_path):
    meta = {}
    tmp = tempfile.mkdtemp(prefix="ph_")
    try:
        with zipfile.ZipFile(phchart_path, "r") as zf:
            zf.extractall(tmp)
        with open(os.path.join(tmp, "chart.json")) as f:
            data = json.load(f)
        meta["chart_name"] = data.get("chart_name", "Sem título")
        meta["columns"]    = data.get("columns", 4)
        meta["note_count"] = len(data.get("notes", []))
        meta["difficulty"] = str(data.get("difficulty", "")).strip()
        cover_arc = data.get("cover_arc")
        if cover_arc:
            src = os.path.join(tmp, cover_arc)
            if os.path.exists(src):
                ext = os.path.splitext(cover_arc)[1]
                cover_name = str(uuid.uuid4()) + ext
                with open(src, "rb") as cf:
                    sb.storage.from_(BUCKET_COVERS).upload(
                        cover_name, cf.read(),
                        {"content-type": "image/jpeg", "upsert": "true"})
                meta["_embedded_cover"] = cover_name
    except Exception as e:
        print(f"extract_meta error: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return meta

def get_user_from_token(req):
    """Valida o Bearer token do Supabase e retorna o user dict ou None."""
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "): return None
    token = auth.split(" ", 1)[1]
    try:
        res = sb.auth.get_user(token)
        return res.user
    except:
        return None

# ── rotas ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/config")
def api_config():
    return jsonify({"anon_key": SUPABASE_ANON})

@app.route("/api/charts")
def api_charts():
    res   = sb.table("charts").select("*").execute()
    db    = res.data or []
    sort  = request.args.get("sort", "recent")
    diff  = request.args.get("diff", "")
    query = request.args.get("q", "").lower()

    if diff:
        db = [c for c in db if diff_color(c.get("difficulty","")) == diff]
    if query:
        db = [c for c in db if query in c.get("chart_name","").lower()
              or query in c.get("author","").lower()]

    if sort == "rating":
        db = sorted(db, key=lambda c: c.get("rating_avg", 0), reverse=True)
    elif sort == "downloads":
        db = sorted(db, key=lambda c: c.get("downloads", 0), reverse=True)
    else:
        db = sorted(db, key=lambda c: c.get("uploaded_at", 0), reverse=True)

    out = []
    for c in db:
        out.append({
            "id":           c["id"],
            "chart_name":   c.get("chart_name", "Sem título"),
            "author":       c.get("author", "anônimo"),
            "difficulty":   c.get("difficulty", ""),
            "diff_label":   diff_label(c.get("difficulty", "")),
            "diff_color":   diff_color(c.get("difficulty", "")),
            "columns":      c.get("columns", 4),
            "note_count":   c.get("note_count", 0),
            "downloads":    c.get("downloads", 0),
            "rating_avg":   round(c.get("rating_avg", 0), 1),
            "rating_count": c.get("rating_count", 0),
            "cover":        public_url(BUCKET_COVERS, c.get("cover")),
            "uploaded_at":  c.get("uploaded_at", 0),
            "user_id":      c.get("user_id", ""),
            "user_email":   c.get("user_email", ""),
        })
    return jsonify(out)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    file       = request.files.get("phchart")
    author     = request.form.get("author", "anônimo").strip()[:40]
    user_id    = request.form.get("user_id", "")
    user_email = request.form.get("user_email", "")
    cover_file = request.files.get("cover")

    if not file:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    if not file.filename.endswith(".phchart"):
        return jsonify({"error": "Apenas arquivos .phchart"}), 400

    cid      = str(uuid.uuid4())[:8]
    filename = cid + ".phchart"
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    file.save(tmp_path)

    with open(tmp_path, "rb") as f:
        sb.storage.from_(BUCKET_CHARTS).upload(
            filename, f.read(),
            {"content-type": "application/octet-stream", "upsert": "true"})

    meta = extract_meta(tmp_path)
    os.remove(tmp_path)
    cover_name = meta.pop("_embedded_cover", None)

    if cover_file and cover_file.filename:
        ext = os.path.splitext(cover_file.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            cover_name = cid + ext
            sb.storage.from_(BUCKET_COVERS).upload(
                cover_name, cover_file.read(),
                {"content-type": "image/" + ext.lstrip("."), "upsert": "true"})

    sb.table("charts").insert({
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
        "user_id":      user_id,
        "user_email":   user_email,
    }).execute()

    return jsonify({"ok": True, "id": cid})

@app.route("/api/edit/<cid>", methods=["POST"])
def api_edit(cid):
    user = get_user_from_token(request)
    if not user:
        return jsonify({"error": "Não autorizado"}), 401

    chart = find_chart(cid)
    if not chart:
        return jsonify({"error": "Chart não encontrado"}), 404

    # só o dono pode editar
    if chart.get("user_id") != user.id and chart.get("user_email") != user.email:
        return jsonify({"error": "Sem permissão"}), 403

    updates = {}
    if request.form.get("chart_name"):
        updates["chart_name"] = request.form["chart_name"].strip()[:80]
    if request.form.get("difficulty"):
        updates["difficulty"] = request.form["difficulty"].strip()

    cover_file = request.files.get("cover")
    if cover_file and cover_file.filename:
        ext = os.path.splitext(cover_file.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            cover_name = cid + "_edit" + ext
            sb.storage.from_(BUCKET_COVERS).upload(
                cover_name, cover_file.read(),
                {"content-type": "image/" + ext.lstrip("."), "upsert": "true"})
            updates["cover"] = cover_name

    if updates:
        sb.table("charts").update(updates).eq("id", cid).execute()

    return jsonify({"ok": True})

@app.route("/api/delete/<cid>", methods=["DELETE"])
def api_delete(cid):
    user = get_user_from_token(request)
    if not user:
        return jsonify({"error": "Não autorizado"}), 401

    chart = find_chart(cid)
    if not chart:
        return jsonify({"error": "Chart não encontrado"}), 404

    if chart.get("user_id") != user.id and chart.get("user_email") != user.email:
        return jsonify({"error": "Sem permissão"}), 403

    # remove arquivos do storage
    try: sb.storage.from_(BUCKET_CHARTS).remove([chart["filename"]])
    except: pass
    if chart.get("cover"):
        try: sb.storage.from_(BUCKET_COVERS).remove([chart["cover"]])
        except: pass

    sb.table("charts").delete().eq("id", cid).execute()
    return jsonify({"ok": True})

@app.route("/api/download/<cid>")
def api_download(cid):
    chart = find_chart(cid)
    if not chart: abort(404)
    sb.table("charts").update({"downloads": chart.get("downloads", 0) + 1}).eq("id", cid).execute()
    url = sb.storage.from_(BUCKET_CHARTS).get_public_url(chart["filename"])
    return redirect(url)

@app.route("/api/rate/<cid>", methods=["POST"])
def api_rate(cid):
    body  = request.get_json(silent=True) or {}
    stars = int(body.get("stars", 0))
    if stars < 1 or stars > 5:
        return jsonify({"error": "estrelas entre 1 e 5"}), 400
    ip    = request.remote_addr
    chart = find_chart(cid)
    if not chart: abort(404)
    ratings = chart.get("ratings") or []
    if isinstance(ratings, str): ratings = json.loads(ratings)
    ratings = [r for r in ratings if r.get("ip") != ip]
    ratings.append({"ip": ip, "stars": stars})
    avg   = round(sum(r["stars"] for r in ratings) / len(ratings), 2)
    count = len(ratings)
    sb.table("charts").update({"ratings": ratings, "rating_avg": avg, "rating_count": count}).eq("id", cid).execute()
    return jsonify({"ok": True, "avg": avg, "count": count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
