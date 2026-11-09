"""イープラスの公演ページを監視し、「受付中」になったらLINEに通知する。

監視するURLは urls.txt に1行ずつ書く（空行と # で始まる行は無視）。

環境変数:
  LINE_CHANNEL_ACCESS_TOKEN  LINE Messaging API のチャネルアクセストークン（長期）
  LINE_USER_ID               通知先の自分のユーザーID（警告・終了予告は自分だけに送る）
  BROADCAST_NOTICES          "true"（既定）なら、開始のお知らせと「受付中」の通知を
                             友だち全員に送る。"false" なら自分だけに送る
  EPLUS_URL                  指定すると urls.txt の代わりにこのURLだけを監視
  DURATION_MINUTES           監視する時間・分（指定すると確認回数を自動で計算する）
  LOOP_COUNT                 1回の実行での確認回数（DURATION_MINUTES がないときだけ使う。既定 1）
  INTERVAL_SECONDS           確認の間隔・秒（既定 60）
  URL_GAP_SECONDS            URLごとの待ち時間・秒（既定 2）
  ERROR_ALERT_THRESHOLD      取得に連続で何回失敗したらLINEで警告するか（既定 5）
  END_NOTICE_REMAINING       残り何回になったら「まもなく終了」をLINEで知らせるか（既定 5）
  ENFORCE_HOURS              "true" のとき、ACTIVE_UNTIL_JST を過ぎたら確認を終了する
  ACTIVE_UNTIL_JST           確認を終える日本時間の時刻（既定 21:30）

使い方:
  python monitor.py          通常の監視
  python monitor.py --test   LINEにテスト通知だけ送る
  python monitor.py --announce 180   「これより180分間、確認を行います」とLINEに送る
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://eplus.jp/sf/detail/0473460021-P0030518P021010?P1=1221"
URLS_FILE = Path(__file__).parent / "urls.txt"

STATUSES = ("受付前", "受付中", "予定枚数終了", "受付終了")
NOTIFY_STATUS = "受付中"

STATE_FILE = Path(__file__).parent / "state.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}


def load_urls() -> list[str]:
    env = os.environ.get("EPLUS_URL")
    if env:
        return [env.strip()]
    if URLS_FILE.exists():
        urls = []
        for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line not in urls:
                urls.append(line)
        if urls:
            return urls
    return [DEFAULT_URL]


def parse_event_name(html: str) -> str:
    """ページのタイトルから公演名を取り出す（通知文に添える）。"""
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.replace(" - イープラス", "").strip()
    return "(公演名不明)"


def parse_tickets(html: str) -> dict[str, str]:
    """ページ内の「受付期間」の直前を券種名、直後を受付状況として取り出す。"""
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    tickets: dict[str, str] = {}
    for i, line in enumerate(lines):
        if not line.startswith("受付期間"):
            continue
        title = lines[i - 1] if i > 0 else "(券種不明)"
        status = next((ln for ln in lines[i + 1 : i + 5] if ln in STATUSES), None)
        if status is None:
            continue
        key, n = title, 2
        while key in tickets:  # 同名の券種がある場合の衝突回避
            key, n = f"{title} #{n}", n + 1
        tickets[key] = status
    return tickets


def _line_post(endpoint: str, payload: dict) -> None:
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    res = requests.post(
        f"https://api.line.me/v2/bot/message/{endpoint}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    res.raise_for_status()


def send_line(text: str) -> None:
    """自分（LINE_USER_ID）だけに送る。エラー警告・終了予告などに使う。"""
    _line_post(
        "push",
        {
            "to": os.environ["LINE_USER_ID"],
            "messages": [{"type": "text", "text": text}],
        },
    )


def send_notice(text: str) -> None:
    """友だち全員に送る（開始のお知らせ・受付中の通知）。
    BROADCAST_NOTICES=false のときは、自分だけに送る。"""
    if os.environ.get("BROADCAST_NOTICES", "true").lower() == "true":
        _line_post("broadcast", {"messages": [{"type": "text", "text": text}]})
    else:
        send_line(text)


def load_state() -> dict[str, str]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def state_key(url: str, title: str) -> str:
    return f"{url}\t{title}"


def check_once(url: str) -> bool:
    """1つのURLを1回確認する。取得に成功したら True。"""
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    tickets = parse_tickets(res.text)
    if not tickets:
        print(f"受付状況を取得できませんでした（ページ構造の変更かアクセス制限の可能性）: {url}")
        return False

    event = parse_event_name(res.text)
    state = load_state()
    restocked = [
        title
        for title, status in tickets.items()
        if status == NOTIFY_STATUS
        and state.get(state_key(url, title)) != NOTIFY_STATUS
    ]

    print(f"[{event}]")
    for title, status in tickets.items():
        print(f"  {status}: {title}")

    if restocked:
        names = "\n".join(f"・{t}" for t in restocked)
        send_notice(
            f"🎫 チケットが「{NOTIFY_STATUS}」になりました！\n"
            f"{event}\n{names}\n\n{url}"
        )
        print("LINEに通知しました")

    # 通知に成功した場合のみ状態を保存（失敗時は次回また通知を試みる）
    prefix = f"{url}\t"
    state = {k: v for k, v in state.items() if not k.startswith(prefix)}
    for title, status in tickets.items():
        state[state_key(url, title)] = status
    save_state(state)
    return True


JST = timezone(timedelta(hours=9))


def past_deadline() -> bool:
    """定期実行のとき、日本時間の終了時刻を過ぎていたら True。"""
    if os.environ.get("ENFORCE_HOURS") != "true":
        return False
    hh, mm = os.environ.get("ACTIVE_UNTIL_JST", "21:30").split(":")
    now = datetime.now(JST)
    return (now.hour, now.minute) >= (int(hh), int(mm))


def notify_safely(text: str) -> None:
    """LINEの送信に失敗しても、監視は止めない。"""
    try:
        send_line(text)
        print("LINEに通知しました")
    except Exception as e:
        print(f"LINE通知に失敗しました: {e}", flush=True)


def format_interval(seconds: int) -> str:
    """確認の間隔を読みやすくする（例: 60 → 1分おき、50 → 50秒おき）。"""
    if seconds % 60 == 0:
        return f"{seconds // 60}分おき"
    return f"{seconds}秒おき"


def build_announcement(
    minutes: int, now: datetime | None = None, interval: int = 60
) -> str:
    now = now or datetime.now(JST)
    end = now + timedelta(minutes=minutes)
    day = "翌" if end.date() != now.date() else ""
    return (
        f"📢 これより{minutes}分間、チケット販売状況の確認を行います。\n"
        f"（{format_interval(interval)}に確認／{day}{end:%H:%M}ごろ終了予定）"
    )


def main() -> int:
    if "--announce" in sys.argv:
        minutes = int(sys.argv[sys.argv.index("--announce") + 1])
        interval = int(os.environ.get("INTERVAL_SECONDS", "60"))
        send_notice(build_announcement(minutes, interval=interval))
        print("開始のお知らせをLINEに送信しました")
        return 0

    if "--test" in sys.argv:
        send_line("【テスト】イープラス在庫通知の設定は完了しています。")
        print("テスト通知を送信しました")
        return 0

    urls = load_urls()
    interval = int(os.environ.get("INTERVAL_SECONDS", "60"))
    url_gap = int(os.environ.get("URL_GAP_SECONDS", "2"))
    if os.environ.get("DURATION_MINUTES"):
        # 監視する時間（分）から、確認の回数を求める（例: 180分・50秒おき → 216回）
        loop_count = max(
            1, int(float(os.environ["DURATION_MINUTES"]) * 60 // max(interval, 1))
        )
    else:
        loop_count = max(1, int(os.environ.get("LOOP_COUNT", "1")))

    print(f"監視URL: {len(urls)}件 / 1回の実行で{loop_count}回確認")
    end_notice = max(1, int(os.environ.get("END_NOTICE_REMAINING", "5")))
    alert_threshold = max(1, int(os.environ.get("ERROR_ALERT_THRESHOLD", "5")))
    fail_streak: dict[str, int] = {}  # URLごとの「連続で取得に失敗した回数」
    alerted: dict[str, bool] = {}  # 警告を送信済みか

    ok_count = 0
    stopped_by_deadline = False
    start = time.monotonic()
    for i in range(loop_count):
        if i > 0:
            # 通信にかかった時間を差し引いて、interval秒ごとの間隔を保つ（ずれを溜めない）
            wait = start + i * interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        if past_deadline():
            print("終了時刻を過ぎたので、確認を終了します")
            stopped_by_deadline = True
            break
        if loop_count > end_notice and i == loop_count - end_notice:
            notify_safely(
                f"⏳ まもなく監視を終了します（あと{end_notice}回の確認で終了）。\n"
                "続けて監視する場合は、もう一度「Run workflow」を押してください。"
            )
        print(f"--- {i + 1}/{loop_count} 回目 ---", flush=True)
        for j, url in enumerate(urls):
            if j > 0:
                time.sleep(url_gap)  # 同時に大量アクセスしない
            try:
                ok = check_once(url)
            except Exception as e:  # 1つのURLの失敗で全体を止めない
                print(f"エラー: {url}: {e}", flush=True)
                ok = False

            if ok:
                ok_count += 1
                if alerted.get(url):
                    notify_safely(f"✅ 受付状況を取得できるようになりました\n{url}")
                    alerted[url] = False
                fail_streak[url] = 0
            else:
                fail_streak[url] = fail_streak.get(url, 0) + 1
                if fail_streak[url] >= alert_threshold and not alerted.get(url):
                    notify_safely(
                        f"⚠️ 受付状況を{fail_streak[url]}回続けて取得できていません\n"
                        f"アクセス制限やページ変更の可能性があります。\n{url}"
                    )
                    alerted[url] = True  # 復旧するまで、同じ警告は繰り返さない

    # 1回も成功しなかった場合だけ、失敗として終了する（時刻切れによる終了は正常）
    return 0 if (ok_count or stopped_by_deadline) else 1


if __name__ == "__main__":
    sys.exit(main())
