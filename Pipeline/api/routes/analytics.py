from fastapi import APIRouter, HTTPException
from datetime import datetime
from collections import Counter
from Pipeline.database.db import transaction

router = APIRouter()


@router.get("/blast/{blast_id}")
def blast_analytics(blast_id: str):
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM blast_log WHERE blast_id = ?", (blast_id,)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="blast_id not found")

    rows = [dict(r) for r in rows]

    total = len(rows)
    sent = sum(1 for r in rows if r["status"] in ("sent", "mocked"))
    failed = sum(1 for r in rows if r["status"] == "failed")

    promo_breakdown = Counter(r["promo_code"] for r in rows if r["promo_code"])

    return {
        "blast_id": blast_id,
        "total": total,
        "total_sent": sent,
        "total_failed": failed,
        "promo_breakdown": dict(promo_breakdown),
        "failures": [
            {"customer_id": r["customer_id"], "reason": r["error_reason"]}
            for r in rows
            if r["status"] == "failed"
        ],
    }
