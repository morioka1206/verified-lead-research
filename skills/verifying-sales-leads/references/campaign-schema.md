# Campaign schema

Use this structure when campaign settings need to be saved or reused.

```json
{
  "id": "campaign-id",
  "research_mode": "standard",
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
  "target_accepted": 50,
  "max_candidates": 100,
  "batch_size": 50,
  "max_pages_per_company": 5
}
```

Suggested `objective` values include `find_importers`, `find_distributors`, `find_wholesalers`, `find_retailers`, `find_hospitality_buyers`, `find_manufacturing_partners`, `find_sales_agents`, `find_strategic_partners`, and `market_landscape`.

Suggested `market.activity_evidence` values are:

- `sales_shipping_customers_warehouse_or_office`: sales, shipping, customers, warehouse, or office in the target market
- `office_required`: a target-market address or office is mandatory
- `explicit_sales_or_distribution`: explicit sales or distribution in the market; an English-language site alone is insufficient

`secondary_buyer_types` are allowed only when the user accepts adjacent roles. `contact_preference` guides collection but never replaces the three-evidence acceptance gate.

`excluded_types` は単なる検索メモではなく、各候補で明示確認する合否条件である。評価JSONには、ここにある全項目と同じ文字列の `exclusion_checks` を作る。確認漏れや `unclear` が1つでもあれば `accepted` にしない。特に卸・販売会社を探す場合は、自社製造会社を除外するのか、製造と販売を兼ねる会社を許容するのかをヒアリングで分けて記録する。

`research_mode` controls only how work is divided and persisted:

- `standard`: up to 50 accepted companies and 100 checked candidates.
- `batch`: up to 1,000 accepted companies and 5,000 checked candidates. `batch_size` defaults to 50 and may be 1–100.

`max_candidates` must be at least `target_accepted`. For a large campaign, use five times the accepted target as a starting ceiling when the likely acceptance rate is unknown. `max_pages_per_company` must not exceed 5 in either mode. Campaign fields guide discovery and evaluation; they never lower the three-evidence acceptance gate.
