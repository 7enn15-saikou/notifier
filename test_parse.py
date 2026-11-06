"""parse_tickets の動作確認（ネットワーク不要）。"""

from monitor import parse_tickets

SOLD_OUT = """
<div class="ticket">
  <h4>先着11/15 17時半キャンセル待ち券受付</h4>
  <p>受付期間:2026/11/3(火・祝)19:00～2026/11/15(日)18:30</p>
  <span>予定枚数終了</span>
  <a>詳細を表示する</a>
</div>
<div class="ticket">
  <h4>先着当日引換券受付</h4>
  <p>受付期間:2026/11/3(火・祝)19:00～2026/11/15(日)18:30</p>
  <span>予定枚数終了</span>
  <a>詳細を表示する</a>
</div>
"""

RESTOCKED = SOLD_OUT.replace("予定枚数終了", "受付中", 1)

a = parse_tickets(SOLD_OUT)
b = parse_tickets(RESTOCKED)

assert a == {
    "先着11/15 17時半キャンセル待ち券受付": "予定枚数終了",
    "先着当日引換券受付": "予定枚数終了",
}, a
assert b["先着11/15 17時半キャンセル待ち券受付"] == "受付中", b
assert b["先着当日引換券受付"] == "予定枚数終了", b

# 通知条件（監視ロジックと同じ式）
def restocked(prev, cur):
    return [t for t, s in cur.items() if s == "受付中" and prev.get(t) != "受付中"]

assert restocked({}, a) == []
assert restocked(a, b) == ["先着11/15 17時半キャンセル待ち券受付"]
assert restocked(b, b) == []  # 受付中が続いても再通知しない

print("OK")
