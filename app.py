import os
import uuid
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pdf-backend")

BUCKET = os.environ.get("S3_BUCKET")
REGION = os.environ.get("AWS_REGION", "eu-north-1")
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES
CORS(app)

# No credentials passed. boto3 picks up the IRSA web identity token that EKS
# projects into the pod at AWS_WEB_IDENTITY_TOKEN_FILE.
s3 = boto3.client("s3", region_name=REGION)


@app.get("/api/health")
def health():
    return jsonify(status="ok", bucket=BUCKET, region=REGION)


@app.get("/api/ready")
def ready():
    """Readiness probe: verifies the IRSA role can actually reach the bucket."""
    try:
        s3.head_bucket(Bucket=BUCKET)
        return jsonify(status="ready"), 200
    except ClientError as e:
        log.warning("readiness failed: %s", e)
        return jsonify(status="not-ready", error=str(e)), 503


@app.post("/api/upload")
def upload():
    if "file" not in request.files:
        return jsonify(error="no file part in request"), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify(error="no file selected"), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify(error="only .pdf files are accepted"), 400

    name = secure_filename(f.filename)
    key = f"uploads/{datetime.utcnow():%Y/%m/%d}/{uuid.uuid4().hex[:8]}-{name}"

    try:
        s3.upload_fileobj(
            f,
            BUCKET,
            key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
    except ClientError as e:
        log.exception("upload failed")
        return jsonify(error=f"upload failed: {e}"), 500

    log.info("uploaded %s", key)
    return jsonify(key=key, filename=name), 201


@app.get("/api/files")
def list_files():
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix="uploads/", MaxKeys=100)
    except ClientError as e:
        log.exception("list failed")
        return jsonify(error=f"list failed: {e}"), 500

    items = [
        {
            "key": o["Key"],
            "filename": o["Key"].rsplit("/", 1)[-1],
            "size": o["Size"],
            "modified": o["LastModified"].isoformat(),
        }
        for o in resp.get("Contents", [])
    ]
    items.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files=items)


@app.get("/api/download")
def download():
    """Returns a short-lived presigned URL so the browser fetches from S3 directly."""
    key = request.args.get("key", "")
    if not key.startswith("uploads/"):
        return jsonify(error="invalid key"), 400

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=300,
        )
    except ClientError as e:
        return jsonify(error=f"could not sign url: {e}"), 500

    return jsonify(url=url, expires_in=300)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error=f"file exceeds {MAX_BYTES // (1024 * 1024)} MB limit"), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
