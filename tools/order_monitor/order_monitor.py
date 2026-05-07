from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import ImageGrab


DEFAULT_CONFIG = Path(__file__).with_name("config.example.json")


@dataclass
class Hit:
    text: str
    reasons: list[str]
    prices: list[float]
    english_ratio: float


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def english_ratio(text: str) -> float:
    letters = sum(1 for c in text if ("a" <= c.lower() <= "z"))
    meaningful = sum(1 for c in text if c.isalnum() or "\u4e00" <= c <= "\u9fff")
    if meaningful == 0:
        return 0.0
    return letters / meaningful


def extract_prices(text: str, currency_keywords: list[str]) -> list[float]:
    prices: list[float] = []

    # Examples: 1000, 1,000, 1.5k, 2k, 1000元, RMB 1000, ¥1000, $200
    pattern = re.compile(
        r"(?i)(?:rmb|usd|cny|¥|￥|\$)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)\s*(k|千|w|万|元|rmb|usd|cny)?"
    )
    currency_lower = [c.lower() for c in currency_keywords]

    for match in pattern.finditer(text):
        raw_num, unit = match.groups()
        start, end = match.span()
        context = text[max(0, start - 8) : min(len(text), end + 8)].lower()

        if not unit and not any(c.lower() in context for c in currency_lower):
            continue

        value = float(raw_num.replace(",", ""))
        unit_l = (unit or "").lower()
        if unit_l in {"k", "千"}:
            value *= 1000
        elif unit_l == "万":
            value *= 10000
        prices.append(value)

    return prices


def split_candidate_messages(text: str) -> list[str]:
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        if current and looks_like_new_message(line):
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


def looks_like_new_message(line: str) -> bool:
    return bool(
        re.match(r"^(\d{1,2}:\d{2}|上午|下午|今天|昨天|\d{4}[-/]\d{1,2}[-/]\d{1,2})", line)
        or re.match(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,24}\s*[:：]", line)
    )


def evaluate_text(text: str, config: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    threshold = float(config["price_threshold"])
    task_keywords = [k.lower() for k in config["task_keywords"]]
    exclude_keywords = [k.lower() for k in config["exclude_keywords"]]

    for chunk in split_candidate_messages(text):
        lowered = chunk.lower()
        if any(k in lowered for k in exclude_keywords):
            continue

        prices = extract_prices(chunk, config.get("currency_keywords", []))
        matched_tasks = [k for k in task_keywords if keyword_matches(lowered, k)]
        reasons: list[str] = []

        high_prices = [p for p in prices if p >= threshold]
        if high_prices:
            reasons.append("price>=" + format_number(threshold))
        if matched_tasks:
            reasons.append("task:" + ", ".join(matched_tasks[:5]))

        if reasons:
            hits.append(
                Hit(
                    text=chunk,
                    reasons=reasons,
                    prices=prices,
                    english_ratio=english_ratio(chunk),
                )
            )

    return hits


def keyword_matches(text: str, keyword: str) -> bool:
    if any("\u4e00" <= c <= "\u9fff" for c in keyword):
        return keyword in text
    escaped = re.escape(keyword)
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text, flags=re.IGNORECASE))


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def capture_text(config: dict[str, Any]) -> str:
    source = config.get("source", "uia").lower()
    if source == "clipboard_drag":
        return capture_text_clipboard_drag(config)
    if source == "uia":
        return capture_text_uia(config)
    if source != "ocr":
        raise RuntimeError(f"Unknown source: {source}. Use 'clipboard_drag', 'uia', or 'ocr'.")
    return capture_text_ocr(config)


def capture_text_clipboard_drag(config: dict[str, Any]) -> str:
    require_expected_foreground_window(config)
    try:
        from pywinauto import keyboard, mouse
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing UI Automation package. Run: python -m pip install -r tools/order_monitor/requirements-order-monitor.txt"
        ) from exc

    region = config.get("capture", {}).get("region")
    if not region:
        raise RuntimeError("clipboard_drag requires capture.region = [left, top, right, bottom].")

    left, top, right, bottom = [int(x) for x in region]
    settings = config.get("clipboard_drag", {})
    margin = int(settings.get("margin", 20))
    direction = settings.get("drag_direction", "bottom_to_top")
    restore_clipboard = bool(settings.get("restore_clipboard", True))

    before_text = get_clipboard_text()

    if direction == "top_to_bottom":
        start = (left + margin, top + margin)
        end = (right - margin, bottom - margin)
    else:
        start = (right - margin, bottom - margin)
        end = (left + margin, top + margin)

    mouse.click(coords=start)
    time.sleep(0.15)
    mouse.press(coords=start)
    time.sleep(0.1)
    mouse.move(coords=end)
    time.sleep(0.2)
    mouse.release(coords=end)
    time.sleep(0.15)
    keyboard.send_keys("^c")
    time.sleep(0.25)

    copied_text = get_clipboard_text() or ""
    if restore_clipboard and before_text is not None:
        set_clipboard_text(before_text)
    return copied_text


def capture_text_uia(config: dict[str, Any]) -> str:
    try:
        import win32gui
        from pywinauto import Desktop
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing UI Automation package. Run: python -m pip install -r tools/order_monitor/requirements-order-monitor.txt"
        ) from exc

    hwnd, title = require_expected_foreground_window(config)

    window = Desktop(backend="uia").window(handle=hwnd)
    texts: list[str] = []

    def add_text(value: str | None) -> None:
        value = normalize_text(value or "")
        if value and value not in texts:
            texts.append(value)

    add_text(title)
    try:
        for item in window.descendants():
            add_text(item.window_text())
    except Exception as exc:
        raise RuntimeError(f"UI Automation could not read active window text: {exc}") from exc

    return "\n".join(texts)


def capture_text_ocr(config: dict[str, Any]) -> str:
    require_expected_foreground_window(config)

    try:
        import pytesseract
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing Python package: pytesseract. Run: python -m pip install -r tools/order_monitor/requirements-order-monitor.txt"
        ) from exc

    tesseract_cmd = config.get("ocr", {}).get("tesseract_cmd")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    region = config.get("capture", {}).get("region")
    bbox = tuple(region) if region else None
    image = ImageGrab.grab(bbox=bbox)

    language = config.get("ocr", {}).get("language", "chi_sim+eng")
    try:
        return pytesseract.image_to_string(image, lang=language)
    except Exception as exc:
        raise RuntimeError(
            "OCR failed. Install Tesseract OCR and the Chinese/English language packs, "
            "or set ocr.tesseract_cmd in config.json."
        ) from exc


def require_expected_foreground_window(config: dict[str, Any]) -> tuple[int, str]:
    try:
        import win32gui
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing pywin32. Run: python -m pip install pywin32") from exc

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("No active foreground window found.")

    title = win32gui.GetWindowText(hwnd)
    title_keywords = config.get("window_title_keywords", [])
    title_matches = not title_keywords or any(k.lower() in title.lower() for k in title_keywords)
    if not title_matches:
        message = f"Active window title does not look like WeCom: {title!r}"
        if config.get("require_window_title_match", True):
            raise RuntimeError(message)
        print(f"Warning: {message}", file=sys.stderr)
    return hwnd, title


def get_clipboard_text(retries: int = 5) -> str | None:
    try:
        import win32clipboard
        import win32con
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing pywin32. Run: python -m pip install pywin32") from exc

    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(0.1)
    return None


def set_clipboard_text(text: str, retries: int = 5) -> None:
    import win32clipboard
    import win32con

    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(0.1)


def hit_id(hit: Hit) -> str:
    basis = normalize_text(hit.text).lower()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def load_seen(path: Path) -> dict[str, datetime]:
    if not path.exists():
        return {}
    seen: dict[str, datetime] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
            seen[obj["id"]] = datetime.fromisoformat(obj["ts"])
        except Exception:
            continue
    return seen


def append_log(path: Path, hit: Hit, id_: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "id": id_,
        "reasons": hit.reasons,
        "prices": hit.prices,
        "english_ratio": round(hit.english_ratio, 3),
        "text": hit.text,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def send_feishu(webhook: str, hit: Hit) -> None:
    if not webhook:
        return
    title = "接单群命中提醒"
    body = (
        f"原因: {', '.join(hit.reasons)}\n"
        f"报价: {', '.join(format_number(p) for p in hit.prices) or '未识别'}\n"
        f"英文占比: {hit.english_ratio:.0%}\n\n"
        f"{hit.text}"
    )
    payload = {
        "msg_type": "text",
        "content": {"text": f"{title}\n{body}"},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise RuntimeError(f"Feishu webhook failed: HTTP {response.status}")


def notify(hit: Hit, config: dict[str, Any]) -> None:
    notifications = config.get("notifications", {})
    send_feishu(notifications.get("feishu_webhook", ""), hit)


def prune_seen(seen: dict[str, datetime], minutes: int) -> dict[str, datetime]:
    cutoff = datetime.now() - timedelta(minutes=minutes)
    return {key: ts for key, ts in seen.items() if ts >= cutoff}


def run_once(text: str, config: dict[str, Any], *, notify_hits: bool) -> int:
    log_path = Path(config["notifications"]["log_file"])
    seen = prune_seen(load_seen(log_path), int(config.get("dedupe_minutes", 60)))
    hits = evaluate_text(text, config)
    fresh = 0

    for hit in hits:
        id_ = hit_id(hit)
        if id_ in seen:
            continue
        fresh += 1
        append_log(log_path, hit, id_)
        if notify_hits:
            notify(hit, config)
        print_hit(hit)

    if fresh == 0:
        print("No fresh hit.")
    return fresh


def print_hit(hit: Hit) -> None:
    print("\n=== HIT ===")
    print("Reasons:", ", ".join(hit.reasons))
    print("Prices:", ", ".join(format_number(p) for p in hit.prices) or "none")
    print("English ratio:", f"{hit.english_ratio:.0%}")
    print(hit.text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local WeCom order monitor MVP.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config JSON.")
    parser.add_argument("--once", action="store_true", help="Capture OCR once and evaluate.")
    parser.add_argument("--loop", action="store_true", help="Keep scanning until Ctrl+C.")
    parser.add_argument("--dry-run-text", help="Evaluate this text without OCR or notification.")
    parser.add_argument("--no-notify", action="store_true", help="Log/print hits without sending notifications.")
    parser.add_argument("--dump-text", help="Write captured text to this file for debugging.")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    if args.dry_run_text:
        return 0 if run_once(args.dry_run_text, config, notify_hits=False) >= 0 else 1

    if not args.once and not args.loop:
        parser.error("Choose --once, --loop, or --dry-run-text.")

    while True:
        try:
            text = capture_text(config)
            if args.dump_text:
                dump_path = Path(args.dump_text)
                dump_path.parent.mkdir(parents=True, exist_ok=True)
                dump_path.write_text(text, encoding="utf-8")
                print(f"Captured text written to {dump_path}")
            run_once(text, config, notify_hits=not args.no_notify)
        except KeyboardInterrupt:
            print("Stopped.")
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(float(config.get("scan_interval_seconds", 5)))


if __name__ == "__main__":
    raise SystemExit(main())
