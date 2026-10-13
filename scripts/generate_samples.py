"""Regenerate the committed SYNTHETIC samples (schema-faithful; not real data)."""
import sys; sys.path.insert(0, "src")
from dop import data as D
D.write_csv(D.generate_backorders(500, seed=7), "data/sample/backorder_sample_SYNTHETIC.csv", D.BACKORDER_COLUMNS)
D.write_csv(D.generate_olist_orders(300, seed=11), "data/sample/olist_orders_sample_SYNTHETIC.csv", D.OLIST_COLUMNS)
print("wrote data/sample/*_SYNTHETIC.csv")
