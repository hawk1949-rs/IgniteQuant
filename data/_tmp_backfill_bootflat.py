import json
import sqlite3

con = sqlite3.connect(r"D:\Cursor\IgniteQuant\data\runtime\falcon_au_sim.sqlite")
cur = con.execute(
    """
    INSERT OR IGNORE INTO decision_event(
      instance_id, decision_id, bar_id, symbol, applied_action,
      target_before, target_after, legacy_signal, payload_json, created_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """,
    (
        "falcon_au_sim",
        "boot-flat:SHFE.au2608:1",
        "boot-flat:SHFE.au2608:1",
        "SHFE.au2608",
        "BOOT_FLATTEN",
        1,
        0,
        0,
        json.dumps(
            {
                "applied_action": "BOOT_FLATTEN",
                "reason_codes": ["BOOT_FLATTEN_PENDING"],
                "note": "策略目标已为0但券商仍有仓，启动时对齐平仓（非止盈/止损）。历史补记：当时意图ID冲突导致委托列表未显示。",
                "fill_id": "fill-66daaee58c",
                "price": 895.7,
            },
            ensure_ascii=False,
        ),
        "2026-07-27T01:54:35.580000+00:00",
    ),
)
con.execute(
    """
    INSERT OR IGNORE INTO order_intent_event(
      instance_id, intent_id, decision_id, symbol, current_position,
      desired_position, urgency, idempotency_key, status,
      reason_codes_json, payload_json, created_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    (
        "falcon_au_sim",
        "intent-bootflat-20260727",
        "boot-flat:SHFE.au2608:1",
        "SHFE.au2608",
        1,
        0,
        "HIGH",
        "boot-flat:SHFE.au2608:1",
        "FILLED",
        json.dumps(["BOOT_FLATTEN_PENDING"]),
        json.dumps(
            {
                "note": "historical backfill for 09:54:35 SELL",
                "linked_fill": "fill-66daaee58c",
            },
            ensure_ascii=False,
        ),
        "2026-07-27T01:54:35.580000+00:00",
    ),
)
con.commit()
print("decision rowcount", cur.rowcount)
print(
    con.execute(
        "select created_at, applied_action, target_before, target_after "
        "from decision_event where decision_id=?",
        ("boot-flat:SHFE.au2608:1",),
    ).fetchone()
)
print(
    con.execute(
        "select intent_id, current_position, desired_position, status "
        "from order_intent_event where intent_id=?",
        ("intent-bootflat-20260727",),
    ).fetchone()
)
