"""Uploads user-submitted images to Cloudinary's free tier.

Why this exists: Vercel's filesystem is read-only except for /tmp, and /tmp
is wiped between invocations, so a file saved locally is gone (or invisible
to other server instances) by the time someone views the page. Cloudinary
gives every upload a permanent, publicly reachable URL, which is what the
site actually needs.

Configuration (set ONE of these in your environment):
  CLOUDINARY_URL = cloudinary://<api_key>:<api_secret>@<cloud_name>
      (this is the single string Cloudinary's own dashboard gives you)
  -- or, separately --
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

If none of these are set, `is_configured()` returns False and callers fall
back to local disk storage (which is fine for local development, but does
not work on Vercel).
"""
import hashlib
import io
import os
import time
import urllib.request
import urllib.error


def _credentials():
    url = os.environ.get("CLOUDINARY_URL", "").strip()
    if url.startswith("cloudinary://"):
        # cloudinary://<api_key>:<api_secret>@<cloud_name>
        rest = url[len("cloudinary://"):]
        try:
            creds, cloud_name = rest.split("@", 1)
            api_key, api_secret = creds.split(":", 1)
        except ValueError:
            return None
        return {"cloud_name": cloud_name, "api_key": api_key, "api_secret": api_secret}

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    if cloud_name and api_key and api_secret:
        return {"cloud_name": cloud_name, "api_key": api_key, "api_secret": api_secret}
    return None


def is_configured():
    return _credentials() is not None


class UploadError(Exception):
    pass


def _multipart_body(fields, file_field_name, filename, file_bytes, content_type):
    boundary = f"----msadiq{secrets_hex()}"
    parts = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n"
                      f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n')
    body = "".join(parts).encode("utf-8")
    body += (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{file_field_name}"; filename="{filename}"\r\n'
             f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
    body += file_bytes
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, boundary


def secrets_hex():
    import secrets
    return secrets.token_hex(8)


def upload_image(file_storage, folder="msadiq"):
    """Upload a Werkzeug FileStorage to Cloudinary. Returns the HTTPS URL.

    Raises UploadError with a human-readable message on any failure, so
    callers can flash it and fall back gracefully instead of crashing.
    """
    creds = _credentials()
    if creds is None:
        raise UploadError("Image hosting is not configured.")

    file_bytes = file_storage.read()
    if not file_bytes:
        raise UploadError("The uploaded file was empty.")

    timestamp = str(int(time.time()))
    # Cloudinary's signature covers every param EXCEPT file/api_key/resource_type,
    # sorted alphabetically, joined as key=value pairs, with api_secret appended.
    params_to_sign = {"folder": folder, "timestamp": timestamp}
    to_sign = "&".join(f"{k}={v}" for k, v in sorted(params_to_sign.items()))
    signature = hashlib.sha1((to_sign + creds["api_secret"]).encode("utf-8")).hexdigest()

    fields = {
        "api_key": creds["api_key"],
        "timestamp": timestamp,
        "folder": folder,
        "signature": signature,
    }
    content_type = file_storage.content_type or "application/octet-stream"
    body, boundary = _multipart_body(fields, "file", file_storage.filename, file_bytes, content_type)

    url = f"https://api.cloudinary.com/v1_1/{creds['cloud_name']}/image/upload"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise UploadError(f"Image upload was rejected ({e.code}): {detail[:200]}")
    except urllib.error.URLError as e:
        raise UploadError(f"Could not reach the image host: {e.reason}")

    secure_url = data.get("secure_url")
    if not secure_url:
        raise UploadError("Image host did not return a URL.")
    return secure_url
