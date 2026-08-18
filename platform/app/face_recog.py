# SPDX-License-Identifier: MIT
"""Server-side face recognition for the visitor kiosk.

Pipeline (best library wins, graceful degradation):
  1. face_recognition (dlib) — HOG/CNN face detection + 128-d face encodings.
     Industry-standard: distance < 0.6 = same person; we use 0.50 (strict).
  2. DeepFace (Facenet512) — used as a SECOND OPINION when available: the
     dlib match must be confirmed by DeepFace.verify before acceptance.
  3. OpenCV — image decoding, illumination normalization (CLAHE) and Haar
     face presence check; also the last-resort detector.

The kiosk (face-api.js) only captures a well-framed portrait; ALL matching
decisions happen here.
"""
from __future__ import annotations

import base64
import contextlib
import io
import logging
import os
import re
import threading

log = logging.getLogger("face_recog")

_LOCK = threading.Lock()          # dlib/tf models are not re-entrant

DIST_MAX = 0.58                   # dlib same-person threshold (industry standard 0.6)
MARGIN_MIN = 0.05                 # winner must beat runner-up by this much
MARGIN_SAFE = 0.45                # margin check only when runner-up is itself plausible
DIST_STRONG = 0.42                # so close that a DeepFace veto is overridden

try:
    import numpy as np
except Exception:                 # pragma: no cover
    np = None

# OpenCV's native (C++) layer writes WARN/INFO lines directly to stderr,
# bypassing Python logging and corrupting the operations console. Force the
# native log level to ERROR *before* the library initializes, then also set
# it via the Python API for older builds that ignore the env var.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
try:
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:        # pragma: no cover — very old OpenCV
        pass
except Exception:                 # pragma: no cover
    cv2 = None

# face_recognition_models 0.3.0 imports pkg_resources, which setuptools ≥ 81
# removed — provide a minimal shim BEFORE the import so dlib matching keeps
# working regardless of the installed setuptools version.
try:
    import pkg_resources  # noqa: F401  (present on setuptools < 81)
except ImportError:       # pragma: no cover — depends on env setuptools
    import importlib.resources as _ilr
    import sys as _sys
    import types as _types

    def _resource_filename(package: str, resource: str) -> str:
        return str(_ilr.files(package) / resource)

    _shim = _types.ModuleType("pkg_resources")
    _shim.resource_filename = _resource_filename  # type: ignore[attr-defined]
    _sys.modules["pkg_resources"] = _shim

# face_recognition prints an installation advisory to stdout (then raises
# SystemExit) when its models package is missing — capture it and emit a
# single structured WARNING through the logger instead of polluting the
# console.
try:
    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
        import face_recognition as fr
except BaseException:             # pragma: no cover — the lib calls quit()
    fr = None                     # (SystemExit) when its models pkg is absent
    log.warning(
        "face_recognition models package not installed — dlib matching "
        "disabled, falling back to OpenCV pipeline. Remediation: "
        "pip install git+https://github.com/ageitgey/face_recognition_models")

_DEEPFACE = None

# OpenCV 5.x no longer bundles the Haar cascade XMLs — we keep our own copies
# in platform/data/models (downloaded from the OpenCV repo).
from pathlib import Path as _Path
_MODELS_DIR = _Path(__file__).resolve().parent.parent / "data" / "models"


def _cascade(name: str):
    """Load a Haar cascade (OpenCV ≤ 4.x only — removed in OpenCV 5)."""
    if not hasattr(cv2, "CascadeClassifier"):
        return None
    for base in (str(_MODELS_DIR) + "/", getattr(getattr(cv2, "data", None), "haarcascades", "")):
        try:
            p = base + name
            if _Path(p).exists():
                c = cv2.CascadeClassifier(p)
                if not c.empty():
                    return c
        except Exception:
            continue
    return None


_YUNET = None


def _yunet():
    """OpenCV FaceDetectorYN (YuNet DNN) — modern detector shipped with
    OpenCV ≥ 4.5.4 / 5.x. Robust to side profiles, dim light, small faces."""
    global _YUNET
    if _YUNET is None:
        _YUNET = False
        try:
            model = _MODELS_DIR / "face_detection_yunet_2023mar.onnx"
            if hasattr(cv2, "FaceDetectorYN_create") and model.exists():
                _YUNET = cv2.FaceDetectorYN_create(str(model), "", (320, 320),
                                                   score_threshold=0.6)
        except Exception:
            _YUNET = False
    return _YUNET or None


def _yunet_faces(rgb) -> int:
    """Count faces YuNet sees in an RGB frame (0 when unavailable)."""
    det = _yunet()
    if det is None:
        return 0
    try:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        with _LOCK:
            det.setInputSize((w, h))
            _, faces = det.detect(bgr)
        return 0 if faces is None else len(faces)
    except Exception:
        return 0


def _deepface():
    """Lazy DeepFace import (TensorFlow load is expensive)."""
    global _DEEPFACE
    if _DEEPFACE is None:
        try:
            from deepface import DeepFace
            _DEEPFACE = DeepFace
        except Exception:         # pragma: no cover
            _DEEPFACE = False
    return _DEEPFACE or None


def available() -> bool:
    return bool(np is not None and fr is not None)


# ---------------------------------------------------------------- decoding
_DATA_URI = re.compile(r"data:image/(?:png|jpe?g|webp|bmp);base64,(.+)", re.I | re.S)


def _decode(data_uri: str):
    """data URI → RGB numpy array (or None)."""
    m = _DATA_URI.match(data_uri or "")
    if not m or np is None or cv2 is None:
        return None
    try:
        buf = np.frombuffer(base64.b64decode(m.group(1)), dtype=np.uint8)
        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return None


def _clahe(rgb):
    """Illumination normalization — helps dim kiosk rooms."""
    try:
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l)
        return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)
    except Exception:
        return rgb


def _haar_locations(rgb):
    """OpenCV Haar fallback → dlib-style (top, right, bottom, left) boxes."""
    try:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        gray = cv2.equalizeHist(gray)
        cascade = _cascade("haarcascade_frontalface_default.xml")
        if cascade is None:
            return []
        faces = cascade.detectMultiScale(gray, 1.08, 4, minSize=(60, 60))
        return [(int(y), int(x + w), int(y + h), int(x)) for (x, y, w, h) in faces]
    except Exception:
        return []


def _mtcnn_locations(rgb):
    """DeepFace/MTCNN neural detector fallback → dlib-style boxes.
    Much more robust than HOG/Haar for webcam portraits."""
    DF = _deepface()
    if DF is None:
        return []
    try:
        faces = DF.extract_faces(rgb[:, :, ::-1], detector_backend="mtcnn",
                                 enforce_detection=False)
        out = []
        for f in faces:
            if float(f.get("confidence") or 0) < 0.80:
                continue
            fa = f["facial_area"]
            x, y, w, h = fa["x"], fa["y"], fa["w"], fa["h"]
            out.append((int(y), int(x + w), int(y + h), int(x)))
        return out
    except Exception:
        return []


def _encodings(rgb, assume_center: bool = False):
    """All dlib 128-d encodings in the image.
    Detection ladder: HOG → CLAHE+HOG → MTCNN (neural) → 2x-upscale HOG →
    OpenCV Haar → (kiosk portraits only) assumed centered face box."""
    with _LOCK:
        locs = fr.face_locations(rgb, number_of_times_to_upsample=1, model="hog")
        if not locs:
            rgb2 = _clahe(rgb)
            locs = fr.face_locations(rgb2, number_of_times_to_upsample=2, model="hog")
            if locs:
                rgb = rgb2
        if not locs:
            locs = _mtcnn_locations(rgb)
        if not locs and cv2 is not None:
            # 2x upscale often recovers small/soft faces for HOG
            up = cv2.resize(rgb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            locs2 = fr.face_locations(up, number_of_times_to_upsample=1, model="hog")
            locs = [(t // 2, r // 2, b // 2, l // 2) for (t, r, b, l) in locs2]
        if not locs and cv2 is not None:
            locs = _haar_locations(rgb)
        if not locs and assume_center:
            # kiosk oval forces the face into the frame centre — encode that
            # region anyway (the client-side neural detector already confirmed
            # a live face was present when the frame was captured)
            h, w = rgb.shape[:2]
            locs = [(int(h * 0.16), int(w * 0.86), int(h * 0.78), int(w * 0.14))]
        if not locs:
            return []
        return fr.face_encodings(rgb, known_face_locations=locs, num_jitters=1)


def encode_face(data_uri: str, assume_center: bool = False):
    """Portrait data URI → single dlib encoding (largest face) or None."""
    rgb = _decode(data_uri)
    if rgb is None or fr is None:
        return None
    encs = _encodings(rgb, assume_center=assume_center)
    return encs[0] if len(encs) else None


def has_face(data_uri: str) -> bool:
    """Lenient human-face presence check for operator attribution.
    Accepts frontal AND side-profile faces, dim lighting, small faces.
    Ladder: YuNet DNN (handles profiles natively) → YuNet on CLAHE frame →
    YuNet on 2x upscale → Haar (OpenCV≤4) → dlib HOG → MTCNN."""
    rgb = _decode(data_uri)
    if rgb is None or cv2 is None:
        return False

    # 1) YuNet on the raw frame
    if _yunet_faces(rgb):
        return True
    # 2) illumination-normalized retry (dim rooms)
    rgb_eq = _clahe(rgb)
    if _yunet_faces(rgb_eq):
        return True
    # 3) small/far face — 2x upscale retry
    try:
        up = cv2.resize(rgb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        if _yunet_faces(up):
            return True
    except Exception:
        pass

    # 4) Haar ladder (only on OpenCV ≤ 4.x installs)
    def _haar_any(img_gray) -> bool:
        for xml in ("haarcascade_frontalface_default.xml",
                    "haarcascade_frontalface_alt2.xml",
                    "haarcascade_profileface.xml"):
            try:
                cascade = _cascade(xml)
                if cascade is None:
                    continue
                if len(cascade.detectMultiScale(img_gray, 1.05, 3, minSize=(40, 40))):
                    return True
                if xml == "haarcascade_profileface.xml":
                    if len(cascade.detectMultiScale(cv2.flip(img_gray, 1), 1.05, 3,
                                                    minSize=(40, 40))):
                        return True
            except Exception:
                continue
        return False

    try:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if _haar_any(cv2.equalizeHist(gray)):
            return True
    except Exception:
        pass
    # 5) dlib HOG detector (moderate rotation tolerance)
    if fr is not None:
        try:
            with _LOCK:
                if fr.face_locations(rgb, number_of_times_to_upsample=2, model="hog"):
                    return True
        except Exception:
            pass
    # 6) MTCNN neural detector — last resort when DeepFace is available
    if _mtcnn_locations(rgb):
        return True
    return False


def _deepface_verify(probe_uri: str, ref_uri: str) -> bool | None:
    """DeepFace second opinion. True/False, or None when unavailable."""
    DF = _deepface()
    if DF is None:
        return None
    p, r = _decode(probe_uri), _decode(ref_uri)
    if p is None or r is None:
        return None
    try:
        with _LOCK:
            res = DF.verify(img1_path=p[:, :, ::-1], img2_path=r[:, :, ::-1],
                            model_name="Facenet512", detector_backend="opencv",
                            enforce_detection=False, silent=True)
        return bool(res.get("verified"))
    except Exception:
        return None


# ---------------------------------------------------------------- matching
def match_visitor(probe_uri: str, candidates: list[dict]):
    """probe portrait vs candidates [{visitor_name, face_photos: [...]}, …].
    Returns (winner_dict | None, info) where info carries diagnostics:
    {distance, margin, verified, reason}."""
    if not available():
        return None, {"reason": "libraries_unavailable"}
    probe = encode_face(probe_uri, assume_center=True)
    if probe is None:
        return None, {"reason": "no_face_in_probe"}

    per: list[tuple[dict, float, str]] = []      # (candidate, best_dist, best_ref_uri)
    for c in candidates:
        best_d, best_uri = 1e9, ""
        for uri in (c.get("face_photos") or [c.get("face_photo", "")]):
            enc = encode_face(uri, assume_center=True)
            if enc is None:
                continue
            d = float(np.linalg.norm(probe - enc))
            if d < best_d:
                best_d, best_uri = d, uri
        if best_d < 1e9:
            per.append((c, best_d, best_uri))
    if not per:
        return None, {"reason": "no_encodable_references"}

    per.sort(key=lambda x: x[1])
    (win, d1, ref_uri), d2 = per[0], (per[1][1] if len(per) > 1 else 1e9)
    margin = d2 - d1
    info = {"distance": round(d1, 3), "margin": round(min(margin, 9.99), 3)}

    if d1 > DIST_MAX:
        info["reason"] = "distance_above_threshold"
        return None, info
    # ambiguity veto only applies when the runner-up is itself a plausible
    # match — a distant runner-up (d2 > MARGIN_SAFE) cannot create ambiguity
    if margin < MARGIN_MIN and d2 <= MARGIN_SAFE:
        info["reason"] = "ambiguous_between_visitors"
        return None, info

    verified = _deepface_verify(probe_uri, ref_uri)
    info["verified"] = verified
    # DeepFace veto only for borderline dlib matches; a very strong dlib
    # distance (< DIST_STRONG) outranks a single Facenet512 disagreement
    if verified is False and d1 >= DIST_STRONG:
        info["reason"] = "deepface_rejected"
        return None, info
    info["reason"] = "ok"
    return win, info
