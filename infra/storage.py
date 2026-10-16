"""Where uploaded files live: local disk, or S3.

This is the module that fixes the real deployment bug. Botfolio writes photos
to static/uploads and 3D models to static/models. On a laptop that is a folder
that persists forever. Inside a Railway container or an ECS task it is a
scratch disk that is **destroyed and recreated on every deploy** — so without
this, pushing a fix on Tuesday deletes every model anyone uploaded on Monday,
silently, with the database still holding rows pointing at files that no longer
exist.

Setting S3_BUCKET moves both folders into a bucket and the problem goes away.
Leaving it unset keeps the current local-disk behaviour exactly as it is.

The two names used throughout are "uploads" (images) and "models" (3D files),
matching the two directories that already exist.
"""

import io
import logging
import mimetypes
import threading

from flask import redirect, send_from_directory, url_for

from infra.settings import settings

log = logging.getLogger("botfolio")

# Set by install() from app.py's own constants, so there is one definition of
# where these directories are rather than two that can drift apart.
_LOCAL_DIRS = {}

_s3 = None
_s3_lock = threading.Lock()

# How long a generated download link stays valid. Long enough to click, short
# enough that a copied URL is not a permanent public handle on the file.
_SIGNED_URL_SECONDS = 3600
_UPLOAD_URL_SECONDS = 6 * 60 * 60


def _client():
    """A boto3 S3 client, created once, or None when running on local disk."""
    global _s3
    if _s3 is not None:
        return _s3 or None
    with _s3_lock:
        if _s3 is not None:
            return _s3 or None
        if not settings.uses_s3:
            _s3 = False
            return None
        try:
            import boto3

            kwargs = {"region_name": settings.s3_region}
            # Only set for S3-compatible services (MinIO in a compose file, or
            # Cloudflare R2). Passing it empty to real AWS breaks signing.
            if settings.s3_endpoint:
                kwargs["endpoint_url"] = settings.s3_endpoint
            # Credentials are deliberately not read here. On ECS boto3 picks up
            # the task role automatically, which is better than any key pair we
            # could put in an environment variable; on Railway it falls back to
            # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from the environment.
            _s3 = boto3.client("s3", **kwargs)
            log.info("uploads backed by s3://%s", settings.s3_bucket)
        except Exception as exc:
            # Falling back to disk keeps the site serving. It will lose files on
            # the next deploy, so this is loud.
            log.error(
                "S3_BUCKET is set but boto3 failed (%s) — falling back to local "
                "disk, uploads will NOT survive a redeploy", type(exc).__name__
            )
            _s3 = False
    return _s3 or None


def _key(bucket, filename):
    """The object key for a file. Mirrors the local folder layout."""
    return f"{bucket}/{filename}"


def _remote(bucket):
    return settings.storage_bucket(bucket)


def _content_type(filename):
    """Guess a type so browsers render images instead of downloading them.

    mimetypes does not know the 3D formats, so those are spelled out. Getting
    STL and OBJ are made explicit because platform MIME maps vary. STEP is
    given its registered type rather than being left to guess, which would make
    a text file browsers happily render inline out of a CAD download.
    """
    explicit = {
        ".stl": "model/stl",
        ".obj": "model/obj",
        ".step": "model/step",
        ".stp": "model/step",
    }
    for suffix, mime in explicit.items():
        if filename.lower().endswith(suffix):
            return mime
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


# --------------------------------------------------------------------------
# The interface app.py uses
# --------------------------------------------------------------------------

def save(bucket, filename, data):
    """Write bytes for `filename` into `bucket`. Returns the filename.

    The return value is what gets stored in the database, and it is the bare
    filename in both modes — never a path or a URL. That is what keeps rows
    written on a laptop readable by a deployment on S3 and the other way
    around; only the resolution of that name changes.
    """
    client = _client()
    if client is None:
        directory = _LOCAL_DIRS[bucket]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(data)
        return filename

    client.put_object(
        Bucket=_remote(bucket),
        Key=_key(bucket, filename),
        Body=data,
        ContentType=_content_type(filename),
        # Uploads never change once written — the filename is a fresh UUID
        # every time — so they can be cached hard. This is most of why serving
        # from a bucket is faster than serving from the app.
        CacheControl="public, max-age=31536000, immutable",
    )
    return filename


def save_image(bucket, filename, pillow_image, **save_kwargs):
    """Store a Pillow image without writing a temporary file.

    app.py re-encodes every uploaded image through Pillow before saving it, and
    Pillow's save() wants a path or a file object. Handing it a BytesIO keeps
    the S3 path from having to write to a disk it does not have.
    """
    buffer = io.BytesIO()
    pillow_image.save(buffer, **save_kwargs)
    return save(bucket, filename, buffer.getvalue())


def url(bucket, filename, external=False):
    """The URL a browser should use for this file.

    Local: the ordinary /static/... path Flask already serves.
    S3: the public bucket or CloudFront URL, so image traffic never touches the
    application at all.

    `external` forces a full scheme-and-host URL. Needed for the og:image and
    twitter:image tags — a relative path there produces no link preview,
    because the crawler reading it has no page to resolve it against. The S3
    branch is already absolute, so the flag only affects local serving.
    """
    if not filename:
        return ""
    if _client() is None:
        return url_for("static", filename=f"{bucket}/{filename}", _external=external)
    base = settings.s3_images_public_url or (
        f"https://{_remote(bucket)}.s3.{settings.s3_region}.amazonaws.com"
    )
    return f"{base}/{_key(bucket, filename)}"


def send(bucket, filename, as_attachment=False):
    """Serve a file, for the download route.

    On S3 this redirects to a short-lived signed URL rather than streaming the
    bytes through the app. A multi-GB model streamed through Flask occupies a
    worker for the whole download, and enough concurrent downloads would stall
    every other request on the instance.
    """
    client = _client()
    if client is None:
        return send_from_directory(_LOCAL_DIRS[bucket], filename,
                                   as_attachment=as_attachment)

    params = {"Bucket": _remote(bucket), "Key": _key(bucket, filename)}
    if as_attachment:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    signed = client.generate_presigned_url(
        "get_object", Params=params, ExpiresIn=_SIGNED_URL_SECONDS
    )
    return redirect(signed)


def delete(bucket, filename):
    """Remove a file. Never raises.

    A file that cannot be deleted must not block deleting the database row that
    references it — the alternative is a design nobody can remove because of a
    storage hiccup. Same reasoning as the original delete_asset().
    """
    if not filename:
        return
    client = _client()
    try:
        if client is None:
            (_LOCAL_DIRS[bucket] / filename).unlink(missing_ok=True)
        else:
            client.delete_object(Bucket=_remote(bucket), Key=_key(bucket, filename))
    except Exception as exc:
        log.warning("could not delete %s/%s (%s)", bucket, filename, type(exc).__name__)


def read(bucket, filename):
    """Return an object's bytes for bounded server-side processing."""
    client = _client()
    if client is None:
        return (_LOCAL_DIRS[bucket] / filename).read_bytes()
    return client.get_object(
        Bucket=_remote(bucket), Key=_key(bucket, filename)
    )["Body"].read()


def read_prefix(bucket, filename, length=4096):
    """Read only enough bytes to validate a large quarantined model's header."""
    client = _client()
    if client is None:
        with (_LOCAL_DIRS[bucket] / filename).open("rb") as handle:
            return handle.read(length)
    return client.get_object(
        Bucket=_remote(bucket), Key=_key(bucket, filename),
        Range=f"bytes=0-{max(0, length - 1)}",
    )["Body"].read()


def size(bucket, filename):
    client = _client()
    if client is None:
        return (_LOCAL_DIRS[bucket] / filename).stat().st_size
    return int(client.head_object(
        Bucket=_remote(bucket), Key=_key(bucket, filename)
    )["ContentLength"])


def presign_upload(bucket, filename, content_type="application/octet-stream"):
    """Authorize one direct browser PUT without exposing storage credentials."""
    client = _client()
    if client is None:
        raise RuntimeError("Direct uploads require configured object storage.")
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": _remote(bucket),
            "Key": _key(bucket, filename),
            "ContentType": content_type,
        },
        ExpiresIn=_UPLOAD_URL_SECONDS,
    )


def initiate_multipart_upload(bucket, filename, content_type="application/octet-stream"):
    """Start a resumable browser upload and return its provider upload id."""
    client = _client()
    if client is None:
        raise RuntimeError("Multipart uploads require configured object storage.")
    response = client.create_multipart_upload(
        Bucket=_remote(bucket),
        Key=_key(bucket, filename),
        ContentType=content_type,
    )
    return response["UploadId"]


def presign_upload_part(bucket, filename, upload_id, part_number):
    """Authorize one numbered part without exposing storage credentials."""
    client = _client()
    if client is None:
        raise RuntimeError("Multipart uploads require configured object storage.")
    return client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": _remote(bucket),
            "Key": _key(bucket, filename),
            "UploadId": upload_id,
            "PartNumber": int(part_number),
        },
        ExpiresIn=_UPLOAD_URL_SECONDS,
    )


def complete_multipart_upload(bucket, filename, upload_id, parts):
    """Assemble uploaded parts into the final quarantined object."""
    client = _client()
    if client is None:
        raise RuntimeError("Multipart uploads require configured object storage.")
    return client.complete_multipart_upload(
        Bucket=_remote(bucket),
        Key=_key(bucket, filename),
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def abort_multipart_upload(bucket, filename, upload_id):
    """Discard incomplete parts. Cleanup callers may safely retry this."""
    if not upload_id:
        return
    client = _client()
    if client is None:
        return
    try:
        client.abort_multipart_upload(
            Bucket=_remote(bucket),
            Key=_key(bucket, filename),
            UploadId=upload_id,
        )
    except Exception as exc:
        log.warning("could not abort multipart upload %s/%s (%s)",
                    bucket, filename, type(exc).__name__)


def promote(source_bucket, destination_bucket, filename):
    """Copy a verified object out of quarantine and remove the original."""
    client = _client()
    if client is None:
        raise RuntimeError("Object promotion requires configured object storage.")
    client.copy_object(
        Bucket=_remote(destination_bucket),
        Key=_key(destination_bucket, filename),
        CopySource={
            "Bucket": _remote(source_bucket),
            "Key": _key(source_bucket, filename),
        },
        ContentType=_content_type(filename),
        MetadataDirective="REPLACE",
    )
    client.delete_object(
        Bucket=_remote(source_bucket), Key=_key(source_bucket, filename)
    )


def health():
    """One line for /readyz describing where uploads are going."""
    client = _client()
    if client is None:
        missing = [name for name, path in _LOCAL_DIRS.items() if not path.exists()]
        if missing:
            # Not an error: the directories are created on first write.
            return f"local disk (pending: {', '.join(missing)})"
        return "local disk"
    try:
        # head_bucket is the cheapest call that proves both credentials and
        # permissions actually work — much better than assuming they do and
        # finding out during someone's upload.
        buckets = sorted(filter(None, {
            settings.s3_bucket_images, settings.s3_bucket_models,
            settings.s3_bucket_quarantine,
        }))
        for bucket in buckets:
            client.head_bucket(Bucket=bucket)
        return ", ".join(f"s3://{bucket}" for bucket in buckets)
    except Exception as exc:
        return f"s3 error: {type(exc).__name__}"


def configure(upload_dir, model_dir):
    """Tell this module where the local folders are.

    Called from app.py, which already defines UPLOAD_DIR and MODEL_DIR. Passing
    them in rather than recomputing them here avoids two modules disagreeing
    about the path after someone moves a directory.
    """
    _LOCAL_DIRS["uploads"] = upload_dir
    _LOCAL_DIRS["models"] = model_dir


def install(app):
    """Expose asset_url() to templates.

    Templates previously wrote url_for('static', filename='uploads/' ~ name)
    directly, which hard-codes the assumption that uploads are served by Flask
    from local disk. Going through this helper is what lets the same template
    render a bucket URL when one is configured.
    """
    app.jinja_env.globals["asset_url"] = url
    return app
