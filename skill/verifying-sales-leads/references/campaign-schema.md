# Campaign schema

Use this structure when campaign settings need to be saved or reused.

```json
{
  "product": {
    "name": "",
    "description": "",
    "category": "",
    "selling_points": [],
    "certifications": [],
    "price_position": null,
    "minimum_order": null,
    "logistics_constraints": [],
    "keywords": [],
    "excluded_keywords": []
  },
  "objective": "find_distributors",
  "markets": [],
  "languages": [],
  "ideal_customer": {
    "types": [],
    "required_signals": [],
    "preferred_signals": [],
    "excluded_types": []
  },
  "verification": {
    "minimum_score": 70,
    "contact_required": false,
    "legal_registry_required": false
  },
  "requested_count": 25
}
```

Suggested `objective` values include `find_importers`, `find_distributors`, `find_wholesalers`, `find_retailers`, `find_hospitality_buyers`, `find_manufacturing_partners`, `find_sales_agents`, `find_strategic_partners`, and `market_landscape`.

Campaign fields guide discovery and evaluation; they do not lower the evidence requirements for accepted records.
