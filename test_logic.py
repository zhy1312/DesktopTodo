# -*- coding: utf-8 -*-
"""todo_app 纯逻辑测试：区域划分、天数格式化、数据存取与容错。"""
import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import todo_app as T


def test_zone_and_fmt():
    assert T.zone_index(-3) == 0
    assert T.zone_index(0) == 0
    assert T.zone_index(1) == 1
    assert T.zone_index(3) == 1
    assert T.zone_index(4) == 1   # 4-7 天归入近档区（规格未定义的空档，避免事项消失）
    assert T.zone_index(7) == 1
    assert T.zone_index(8) == 2
    assert T.zone_index(365) == 2
    assert T.fmt_days(0) == "今天"
    assert T.fmt_days(-2) == "逾期2天"
    assert T.fmt_days(5) == "5天"
    print("[1/3] 区域划分与天数格式化 OK")


def test_storage():
    tmp = tempfile.mkdtemp()
    T.DATA_DIR = tmp
    T.DATA_FILE = os.path.join(tmp, "todos.json")
    T.SETTINGS_FILE = os.path.join(tmp, "settings.json")
    today = dt.date.today()
    todos = [
        {"id": "a1", "text": "还书", "date": today.isoformat(), "created": "2026-10-14T09:00:00"},
        {"id": "a2", "text": "交周报", "date": (today + dt.timedelta(days=2)).isoformat(), "created": "2026-10-14T09:01:00"},
        {"id": "a3", "text": "双十一", "date": (today + dt.timedelta(days=30)).isoformat(), "created": "2026-10-14T09:02:00"},
        {"id": "a4", "text": "补数据", "date": (today - dt.timedelta(days=3)).isoformat(), "created": "2026-10-14T09:03:00"},
        {"id": "bad", "text": "坏日期", "date": "not-a-date"},
        {"id": "bad2", "text": "", "date": today.isoformat()},
    ]
    assert T.save_todos(todos)
    assert os.path.exists(T.DATA_FILE) and os.path.getsize(T.DATA_FILE) > 0
    loaded = T.load_todos()
    assert len(loaded) == 4, "非法条目应被过滤，实际 %d 条" % len(loaded)

    # 分组与排序：逾期在前、今天在后；组内按剩余天数升序
    groups = T.group_todos(loaded)
    assert [t["id"] for _, t in groups[0]] == ["a4", "a1"], groups[0]
    assert [t["id"] for _, t in groups[1]] == ["a2"]
    assert [t["id"] for _, t in groups[2]] == ["a3"]

    # 天数计算
    assert T.days_left(today.isoformat()) == 0
    assert T.days_left((today + dt.timedelta(days=8)).isoformat()) == 8

    # 设置持久化
    assert T.save_json(T.SETTINGS_FILE, {"pinned": True, "geometry": [10, 20, 320, 470]})
    s = T.load_json(T.SETTINGS_FILE, {})
    assert s["geometry"][2] == 320

    # 损坏文件容错
    with open(T.DATA_FILE, "w", encoding="utf-8") as f:
        f.write("{broken json")
    assert T.load_todos() == []
    assert T.load_json(T.DATA_FILE, {"fallback": 1})["fallback"] == 1
    print("[2/3] 存取/容错/分组排序 OK")


def test_days_across_days():
    """模拟跨天：today+1 的事项从‘3天内’进入‘当天’区。"""
    today = dt.date.today()
    d1 = (today + dt.timedelta(days=1)).isoformat()
    assert T.zone_index(T.days_left(d1)) == 1  # 今天看：明天 -> 3天内
    # 明天看（days_left 基准变化）等价于用今天的日期计算 today-today = 0
    assert T.zone_index(T.days_left(today.isoformat())) == 0
    print("[3/3] 跨天区域迁移逻辑 OK")


if __name__ == "__main__":
    test_zone_and_fmt()
    test_storage()
    test_days_across_days()
    print("ALL TESTS PASSED")
