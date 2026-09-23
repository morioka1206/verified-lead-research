# Campaign schema

Use this structure when campaign settings need to be saved or reused.

```json
{
  "id": "campaign-id",
  "product": {
    "name": "",
    "description": "",
    "keywords": []
  },
  "market": {
    "name": "",
    "keywords": [],
    "activity_evidence": "sales_shipping_customers_warehouse_or_office"
  },
  "objective": "find_distributors",
  "buyer_types": [
    {
      "name": "",
      "keywords": []
    }
  ],
  "secondary_buyer_types": [],
  "excluded_types": [],
  "excluded_companies": [],
  "contact_preference": "public_email_then_optional_form",
  "target_accepted": 30,
  "max_candidates": 100,
  "max_pages_per_company": 5
}
```

Suggested `objective` values include `find_importers`, `find_distributors`, `find_wholesalers`, `find_retailers`, `find_hospitality_buyers`, `find_manufacturing_partners`, `find_sales_agents`, `find_strategic_partners`, and `market_landscape`.

Suggested `market.activity_evidence` values are:

- `sales_shipping_customers_warehouse_or_office`: sales, shipping, customers, warehouse, or office in the target market
- `office_required`: a target-market address or office is mandatory
- `explicit_sales_or_distribution`: explicit sales or distribution in the market; an English-language site alone is insufficient

`secondary_buyer_types` are allowed only when the user accepts adjacent roles. `contact_preference` guides collection but never replaces the three-evidence acceptance gate.

`target_accepted` must not exceed 30 in v1, `max_candidates` must not exceed 100, and `max_pages_per_company` must not exceed 5. Campaign fields guide discovery and evaluation; they never lower the three-evidence acceptance gate.
