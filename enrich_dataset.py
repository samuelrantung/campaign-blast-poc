import pandas as pd
import numpy as np
from datetime import timedelta

INPUT = "retail_sales_dataset.csv"
OUTPUT = "retail_sales_enriched.csv"
NEW_ROWS = 2000
SEED = 42

df = pd.read_csv(INPUT)
df.columns = df.columns.str.lower().str.replace(' ', '_')
df = df.rename(columns={"total_amount": "order_value", "date": "purchase_date"})
df["phone_number"] = "+6282187792052"
df["created_at"] = "2023-01-01"

# Customer profile: lock gender and age per customer from original data
profile = df.set_index("customer_id")[["gender", "age"]].to_dict(orient="index")

rng = np.random.default_rng(SEED)

categories = df["product_category"].unique()
price_map = {
    "Beauty":      (10, 500),
    "Clothing":    (50, 1000),
    "Electronics": (10, 500),
}

date_start = pd.Timestamp("2023-01-01")
date_end   = pd.Timestamp("2024-01-01")
date_range_days = (date_end - date_start).days

customer_ids = df["customer_id"].tolist()  # sample from original 1000
max_txn_id = df["transaction_id"].max()

rows = []
for i in range(NEW_ROWS):
    cust_id = customer_ids[rng.integers(0, len(customer_ids))]
    cat = categories[rng.integers(0, len(categories))]
    lo, hi = price_map.get(cat, (10, 500))
    price = int(rng.integers(lo, hi + 1))
    qty = int(rng.integers(1, 6))
    days_offset = int(rng.integers(0, date_range_days))
    purchase_date = (date_start + timedelta(days=days_offset)).strftime("%Y-%m-%d")

    rows.append({
        "transaction_id":   max_txn_id + i + 1,
        "purchase_date":    purchase_date,
        "customer_id":      cust_id,
        "gender":           profile[cust_id]["gender"],
        "age":              profile[cust_id]["age"],
        "product_category": cat,
        "quantity":         qty,
        "price_per_unit":   price,
        "order_value":      price * qty,
        "phone_number":     "+6282187792052",
        "created_at":       "2023-01-01",
    })

synthetic = pd.DataFrame(rows)
combined = pd.concat([df, synthetic], ignore_index=True)

combined = combined[[
    "transaction_id", "purchase_date", "customer_id",
    "gender", "age", "product_category",
    "quantity", "price_per_unit", "order_value",
    "phone_number", "created_at",
]]

combined.to_csv(OUTPUT, index=False)

txn_per_customer = combined.groupby("customer_id").size()
print(f"Saved to {OUTPUT}")
print(f"  Total rows:        {len(combined)}")
print(f"  Unique customers:  {combined['customer_id'].nunique()}")
print(f"  Txn per customer — min: {txn_per_customer.min()}, max: {txn_per_customer.max()}, avg: {txn_per_customer.mean():.1f}")
print(f"  Gender consistency: {(combined.groupby('customer_id')['gender'].nunique() == 1).all()}")
print(f"  Age consistency:    {(combined.groupby('customer_id')['age'].nunique() == 1).all()}")
