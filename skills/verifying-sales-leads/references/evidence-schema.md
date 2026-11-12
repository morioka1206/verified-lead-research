# Evidence record schema

Produce one record per canonical company domain.

```json
{
  "company_name": "",
  "canonical_url": "",
  "final_url": "",
  "country": null,
  "company_type": null,
  "company_overview_ja": "",
  "claims": [
    {
      "type": "product",
      "evidence_url": "",
      "evidence_text_original": "",
      "evidence_text_ja": ""
    }
  ],
  "emails": [
    {
      "email": "",
      "source_url": ""
    }
  ],
  "contact_forms": [
    {
      "url": "",
      "verification": "form_found"
    }
  ],
  "assessment_recommendation": "review",
  "verification_status": "review",
  "rejection_reason": null,
  "uncertainties": [],
  "checked_at": "",
  "discovery": {
    "query": "",
    "source_url": ""
  }
}
```

## Allowed status values

- `verification_status`: `accepted`, `review`, `rejected`, `blocked`
- claim `type`: `product`, `buyer_role`, `target_market`
- contact-form `verification`: `form_found` (`linked_from_official_site` appears only in older saved crawls; external links are no longer recorded)

## Acceptance invariant

An `accepted` record requires `assessment_recommendation: accepted`, non-empty `company_name`, `canonical_url`, and `checked_at`, plus at least one independently verified claim of each required type. Each `evidence_text_original` must occur in the retrieved text for its exact `evidence_url`. Email and contact form fields are optional and must never be guessed. Contact forms must be on the company's own site. Emails are kept only at the company's domain (or a subdomain), a same-brand domain under another suffix (e.g. `mashsteak.de` / `mashsteak.dk`), or a common free-mail provider; addresses at unrelated domains, such as authorities named on accessibility or imprint pages, go to `excluded_emails` with `reason: third_party_domain` and are not exported as contacts. The finalizer may downgrade an AI assessment but never promote `review` or `rejected`.
