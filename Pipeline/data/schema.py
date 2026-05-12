from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Transaction:
    transaction_id: str
    purchase_date: datetime
    order_value: float
    product_category: str
    quantity: int
    price_per_unit: float


@dataclass
class Customer:
    customer_id: str
    customer_name: str
    phone_number: str           # E.164 format after normalization
    created_at: datetime
    gender: Optional[str]
    age: Optional[int]
    transactions: List[Transaction] = field(default_factory=list)

    @property
    def last_purchase_date(self) -> Optional[datetime]:
        if not self.transactions:
            return None
        return max(t.purchase_date for t in self.transactions)

    @property
    def total_spend(self) -> float:
        return sum(t.order_value for t in self.transactions)

    @property
    def purchase_count(self) -> int:
        return len(self.transactions)

    @property
    def avg_order_value(self) -> float:
        if not self.transactions:
            return 0.0
        return self.total_spend / self.purchase_count

    @property
    def top_category(self) -> Optional[str]:
        if not self.transactions:
            return None
        counts: dict[str, int] = {}
        for t in self.transactions:
            counts[t.product_category] = counts.get(t.product_category, 0) + 1
        return max(counts, key=counts.get)
