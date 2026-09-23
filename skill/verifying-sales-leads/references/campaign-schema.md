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
    "keywords": []
  },
  "objective": "find_distributors",
  "buyer_types": [
    {
      "name": "",
      "keywords": []
    }
  ],
  "excluded_types": [],
  "target_accepted": 30,
  "max_candidates": 100,
  "max_pages_per_company": 5
}
```

Suggested `objective` values include `find_importers`, `find_distributors`, `find_wholesalers`, `find_retailers`, `find_hospitality_buyers`, `find_manufacturing_partners`, `find_sales_agents`, `find_strategic_partners`, and `market_landscape`.

`target_accepted` must not exceed 30 in v1, `max_candidates` must not exceed 100, and `max_pages_per_company` must not exceed 5. Campaign fields guide discovery and evaluation; they never lower the three-evidence acceptance gate.
