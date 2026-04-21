"""
PhCharts — servidor Flask com Supabase (storage permanente)
  Variáveis de ambiente necessárias:
    SUPABASE_URL   → ex: https://xyzxyz.supabase.co
    SUPABASE_KEY   → chave "service_role" (não a anon!)
"""

import os, json, zipfile, shutil, tempfile, uuid, time
from flask import Flask, request, jsonify, send_from_directory, redirect, abort
from supabase import create_client, Client

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Supabase ──────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
sb: Client   = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_CHARTS = "charts"   # bucket para .phchart
BUCKET_COVERS = "covers"   # bucket para capas

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

# ── banco de dados: Supabase (tabela "charts") ────────────────────────
def load_db():
    res = sb.table("charts").select("*").execute()
    return res.data or []

def find_chart(cid):
    res = sb.table("charts").select("*").eq("id", cid).execute()
    return res.data[0] if res.data else None

def public_url(bucket, filename):
    if not filename:
        return None
    return sb.storage.from_(bucket).get_public_url(filename)

# ── extrair metadados do .phchart ─────────────────────────────────────
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
        # capa embutida no zip?
        cover_arc = data.get("cover_arc")
        if cover_arc:
            src = os.path.join(tmp, cover_arc)
            if os.path.exists(src):
                ext = os.path.splitext(cover_arc)[1]
                cover_name = str(uuid.uuid4()) + ext
                with open(src, "rb") as cf:
                    sb.storage.from_(BUCKET_COVERS).upload(
                        cover_name, cf.read(),
                        {"content-type": "image/jpeg", "upsert": "true"}
                    )
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
    db    = load_db()
    sort  = request.args.get("sort", "recent")
    diff  = request.args.get("diff", "")
    query = request.args.get("q", "").lower()

    if diff:
        db = [c for c in db if diff_color(c.get("difficulty", "")) == diff]
    if query:
        db = [c for c in db if query in c.get("chart_name", "").lower()
              or query in c.get("author", "").lower()]

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
        })
    return jsonify(out)

# ── upload ────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def api_upload():
    file       = request.files.get("phchart")
    author     = request.form.get("author", "anônimo").strip()[:40]
    cover_file = request.files.get("cover")

    if not file:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    if not file.filename.endswith(".phchart"):
        return jsonify({"error": "Apenas arquivos .phchart"}), 400

    cid      = str(uuid.uuid4())[:8]
    filename = cid + ".phchart"

    # salva temporariamente para extrair metadados
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    file.save(tmp_path)

    # faz upload do .phchart para o Supabase Storage
    with open(tmp_path, "rb") as f:
        sb.storage.from_(BUCKET_CHARTS).upload(
            filename, f.read(),
            {"content-type": "application/octet-stream", "upsert": "true"}
        )

    meta = extract_meta(tmp_path)
    os.remove(tmp_path)

    cover_name = meta.pop("_embedded_cover", None)

    # capa enviada manualmente sobrepõe a embutida
    if cover_file and cover_file.filename:
        ext = os.path.splitext(cover_file.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            cover_name = cid + ext
            sb.storage.from_(BUCKET_COVERS).upload(
                cover_name, cover_file.read(),
                {"content-type": "image/" + ext.lstrip("."), "upsert": "true"}
            )

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
    }).execute()

    return jsonify({"ok": True, "id": cid})

# ── download ──────────────────────────────────────────────────────────
@app.route("/api/download/<cid>")
def api_download(cid):
    chart = find_chart(cid)
    if not chart:
        abort(404)

    # incrementa contador
    sb.table("charts").update(
        {"downloads": chart.get("downloads", 0) + 1}
    ).eq("id", cid).execute()

    # redireciona para URL pública do Supabase Storage
    url = sb.storage.from_(BUCKET_CHARTS).get_public_url(chart["filename"])
    return redirect(url)

# ── rating ────────────────────────────────────────────────────────────
@app.route("/api/rate/<cid>", methods=["POST"])
def api_rate(cid):
    body  = request.get_json(silent=True) or {}
    stars = int(body.get("stars", 0))
    if stars < 1 or stars > 5:
        return jsonify({"error": "estrelas entre 1 e 5"}), 400

    ip    = request.remote_addr
    chart = find_chart(cid)
    if not chart:
        abort(404)

    ratings = chart.get("ratings") or []
    if isinstance(ratings, str):
        ratings = json.loads(ratings)

    ratings = [r for r in ratings if r.get("ip") != ip]
    ratings.append({"ip": ip, "stars": stars})

    avg   = round(sum(r["stars"] for r in ratings) / len(ratings), 2)
    count = len(ratings)

    sb.table("charts").update({
        "ratings":      ratings,
        "rating_avg":   avg,
        "rating_count": count,
    }).eq("id", cid).execute()

    return jsonify({"ok": True, "avg": avg, "count": count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
