# Evidence record schema

Produce one record per canonical company domain.

```json
{
  "company_name": "",
  "canonical_url": "",
  "final_url": "",
  "country": null,
  "company_type": null,
  "product_fit": "unknown",
  "fit_score": 0,
  "claims": [
    {
      "claim": "",
      "evidence_url": "",
      "evidence_text": ""
    }
  ],
  "email": null,
  "email_source_url": null,
  "contact_form_url": null,
  "site_status": "active",
  "verification_status": "review",
  "rejection_reason": null,
  "uncertainties": [],
  "checked_at": ""
}
```

## Allowed status values

- `site_status`: `active`, `blocked`, `dead`, `parked`, `unknown`
- `verification_status`: `accepted`, `review`, `rejected`, `blocked`
- `product_fit`: `high`, `medium`, `low`, `unknown`

## Acceptance invariant

An `accepted` record must have non-empty `company_name`, `canonical_url`, `checked_at`, and at least one claim whose `evidence_url` was retrieved and whose `evidence_text` occurs in that page. Campaign-specific thresholds may require stronger evidence.
