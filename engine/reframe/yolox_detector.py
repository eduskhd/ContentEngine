"""YOLOX-nano person / object detector via ONNX Runtime.

Model: yolox_nano.onnx  (Apache-2.0, Megvii)
Download: python scripts/download_models.py

Input:  BGR frames (any size)
Output: per-frame list of (x, y, w, h, score, class_id)

YOLOX ONNX uses raw float32 in [0, 255] — no mean subtraction.
Letterbox pads to INPUT_SIZE=(416, 416) preserving aspect ratio.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np

_MODEL_DIR = Path(__file__).parent.parent.parent / "models"
_MODEL_PATH = _MODEL_DIR / "yolox_nano.onnx"
_INPUT_SIZE = (416, 416)
_CONF_THRESHOLD = 0.30
_NMS_THRESHOLD = 0.45
_PERSON_CLASS = 0    # COCO class 0 = person


def model_available() -> bool:
    return _MODEL_PATH.exists()


# ── Pre / post processing ─────────────────────────────────────────────────────

def _letterbox(
    img: np.ndarray,
    target: tuple[int, int] = _INPUT_SIZE,
) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Letterbox-resize preserving aspect ratio.  Padding value=114.

    Returns (padded_img, scale, (pad_left, pad_top)).
    """
    import cv2
    h, w = img.shape[:2]
    th, tw = target
    scale = min(tw / w, th / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((th, tw, 3), 114, dtype=np.uint8)
    pad_l = (tw - nw) // 2
    pad_t = (th - nh) // 2
    canvas[pad_t:pad_t + nh, pad_l:pad_l + nw] = resized
    return canvas, scale, (pad_l, pad_t)


def _grid_decode(
    output: np.ndarray,       # [N, 5 + num_classes]  raw YOLOX grid predictions
    input_size: tuple[int, int] = _INPUT_SIZE,
    p6: bool = False,
) -> np.ndarray:
    """Apply YOLOX grid decode to raw ONNX output.

    The simplified YOLOX ONNX export outputs grid-relative predictions that
    require grid offset + stride multiplication to get absolute pixel coords.
    Output of this function has the same shape with cols 0-3 as absolute
    (cx, cy, w, h) in input_size pixels.
    """
    strides = [8, 16, 32, 64] if p6 else [8, 16, 32]
    h_in, w_in = input_size

    grids, exp_strides = [], []
    for stride in strides:
        hs, ws = h_in // stride, w_in // stride
        xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
        grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(grid)
        exp_strides.append(np.full((*grid.shape[:2], 1), stride))

    grids = np.concatenate(grids, axis=1)         # [1, N, 2]
    exp_strides = np.concatenate(exp_strides, axis=1)  # [1, N, 1]

    decoded = output.copy()
    decoded[..., :2] = (decoded[..., :2] + grids[0]) * exp_strides[0]
    decoded[..., 2:4] = np.exp(decoded[..., 2:4]) * exp_strides[0]
    return decoded


def _decode_output(
    output: np.ndarray,        # [N, 5 + num_classes] — AFTER grid_decode
    scale: float,
    pad_xy: tuple[int, int],
    orig_w: int,
    orig_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert decoded YOLOX predictions to (boxes_xywh, class_scores) in orig coords."""
    pad_l, pad_t = pad_xy
    cx = (output[:, 0] - pad_l) / scale
    cy = (output[:, 1] - pad_t) / scale
    bw = output[:, 2] / scale
    bh = output[:, 3] / scale

    x1 = np.clip(cx - bw / 2, 0, orig_w)
    y1 = np.clip(cy - bh / 2, 0, orig_h)
    x2 = np.clip(cx + bw / 2, 0, orig_w)
    y2 = np.clip(cy + bh / 2, 0, orig_h)
    boxes = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1)

    obj_conf = output[:, 4:5]
    class_scores = output[:, 5:] * obj_conf
    return boxes, class_scores


def _nms(boxes_x1y1x2y2: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Greedy NMS; returns kept index list."""
    x1, y1, x2, y2 = (boxes_x1y1x2y2[:, i] for i in range(4))
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        iou = (np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)) / (
            areas[i] + areas[order[1:]] - (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0) + 1e-6
        )
        order = order[1:][iou <= iou_thr]
    return keep


# ── Public API ────────────────────────────────────────────────────────────────

# Detection = (x, y, w, h, score, class_id)
Detection = tuple[int, int, int, int, float, int]


def detect_objects(
    frames: list[np.ndarray],
    classes: list[int] | None = None,
    conf_threshold: float = _CONF_THRESHOLD,
) -> list[list[Detection]]:
    """Run YOLOX-nano on a batch of BGR frames.

    classes: COCO class IDs to keep (default: [0] = person only).
    Returns one list per frame; each element is (x, y, w, h, score, class_id).
    """
    if not model_available() or not frames:
        return [[] for _ in frames]

    if classes is None:
        classes = [_PERSON_CLASS]

    try:
        import onnxruntime as ort
    except ImportError:
        return [[] for _ in frames]

    sess = ort.InferenceSession(
        str(_MODEL_PATH),
        providers=["CPUExecutionProvider"],
    )
    input_name = sess.get_inputs()[0].name

    results: list[list[Detection]] = []

    for frame in frames:
        orig_h, orig_w = frame.shape[:2]
        padded, scale, pad_xy = _letterbox(frame, _INPUT_SIZE)
        # YOLOX takes float32 in [0,255], CHW, batch=1
        blob = padded.astype(np.float32).transpose(2, 0, 1)[None]

        raw = sess.run(None, {input_name: blob})[0][0]  # [N, 5+C]
        if raw.size == 0:
            results.append([])
            continue

        decoded = _grid_decode(raw, _INPUT_SIZE)
        boxes, class_scores = _decode_output(decoded, scale, pad_xy, orig_w, orig_h)

        frame_dets: list[Detection] = []
        for cls_id in classes:
            cls_scores = class_scores[:, cls_id]
            mask = cls_scores > conf_threshold
            if not mask.any():
                continue
            fboxes = boxes[mask]
            fscores = cls_scores[mask]
            x1y1x2y2 = np.column_stack([fboxes[:, 0], fboxes[:, 1],
                                         fboxes[:, 0] + fboxes[:, 2],
                                         fboxes[:, 1] + fboxes[:, 3]])
            keep = _nms(x1y1x2y2, fscores, _NMS_THRESHOLD)
            for idx in keep:
                x, y, w, h = (int(v) for v in fboxes[idx])
                frame_dets.append((x, y, w, h, float(fscores[idx]), cls_id))

        results.append(frame_dets)

    return results


def detect_persons(
    frames: list[np.ndarray],
    conf_threshold: float = _CONF_THRESHOLD,
) -> list[list[tuple[int, int, int, int, float]]]:
    """Convenience wrapper: persons only, returns (x, y, w, h, score)."""
    raw = detect_objects(frames, classes=[_PERSON_CLASS], conf_threshold=conf_threshold)
    return [[(d[0], d[1], d[2], d[3], d[4]) for d in frame_dets] for frame_dets in raw]
