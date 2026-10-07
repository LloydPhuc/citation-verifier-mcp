# DOI, complete citations and online sources

`verify_reference` checks one reference without a downloaded paper. Its `reference`
argument accepts a DOI, a DOI resolver URL, a complete citation string, or an object
with `doi`, `title`, `authors` (list of names), `year`, `publisher`,
`container_title` and/or `citation`. Supply `claim` to also acquire public full text
and use the existing BM25 → NLI → provenance → verdict pipeline.

```json
{"reference": "https://doi.org/10.1371/journal.pmed.0020124"}
```

```json
{
  "reference": {
    "title": "Why Most Published Research Findings Are False",
    "authors": ["Ioannidis, J. P. A."],
    "year": 2005
  },
  "claim": "The probability that a research finding is true depends on statistical power."
}
```

`verify_claim` and `verify_claims` retain their existing string source schemas.
Their sources now also accept DOI/DOI URLs, full citation strings and public
scholarly HTML URLs. Structured references belong in `verify_reference`.

```json
{
  "claim": "The paper studies research findings and statistical power.",
  "source": "10.1371/journal.pmed.0020124"
}
```

## Reference identity and claim support

| Field | Meaning |
|---|---|
| `reference_exists: true` | A corresponding registry record was retrieved. This is not a scientific credibility assessment. |
| `reference_exists: null` | Existence was not established. No negative authenticity assertion is made. |
| `status: VERIFIED` | DOI record found or conservative citation match established; supplied structured fields match. |
| `status: METADATA_MISMATCH` | A work exists, but supplied structured title, author, year, publisher or journal differs. Outer verdict is `WARN`. |
| `status: PARTIALLY_VERIFIED` | Registry lacks a supplied field, or a DOI-containing citation could not be corroborated. Outer verdict is `WARN`. |
| `status: AMBIGUOUS / NO_CONFIDENT_MATCH` | Candidates do not identify one work confidently. Outer verdict is `ABSTAIN`. |
| `status: NOT_FOUND` | Queried registries did not return a match. Coverage is incomplete; this does not prove fabrication. |
| `status: SERVICE_UNAVAILABLE` | A service failed or returned inconsistent data. This is distinct from no match. |
| `claim_verification` | Independent existing claim response, present when `claim` was supplied. |

DOI lookup tries Crossref, then DataCite if needed. DOI-free lookup searches up to
five Crossref candidates. Titles must match after case/punctuation normalization;
multiple matching records require supplied metadata to distinguish them. Structured
authors accept matching surnames and initials. Publication year may match online
or print publication. Metadata comparisons are conservative and can warn on name
variants; missing fields remain unknown.

Free-form citation matching corroborates title and available year plus at least
one author surname. It does **not** parse and validate every author or publisher
in arbitrary citation styles. Use the structured object for explicit field checks.
A raw citation containing an uncorroborated real DOI cannot authorize claim
verification merely because the DOI exists. Unknown, ambiguous or mismatched
references abstain before content acquisition.

## Acquiring evidence

The loader tries a bounded list of registry full-text links, optional Unpaywall OA
locations, publisher landing pages and the DOI resolver. A publisher HTML page may
declare a `citation_pdf_url`; at most one PDF fallback is followed per candidate.
Sources and redirect targets must resolve to public addresses. Downloads have
size limits and connection/read timeouts. New web acquisitions respect robots.txt
and use no browser login, cookies, JavaScript execution or paywall bypass.

Static HTML is accepted only when an article/main or supported article-body
container contains at least 1,200 normalized characters and two recognizable
scientific section headings. Navigation, scripts, abstracts, related content and
bibliography sections are excluded where recognized. These are heuristics:
publisher layouts, essays without standard sections, localized headings, partial
pages and JavaScript-rendered articles may abstain. Accepted HTML is not a
guarantee that every section, equation or table was recovered.

DOI-resolved HTML must expose a matching citation DOI or matching citation title.
DOI-resolved PDFs must corroborate the DOI or title in the first 4,000 extracted
characters. Conservative identity checks can reject legitimate extraction/layout
variants. A verified reference with inaccessible or unusable full text still
returns a claim `ABSTAIN`; a metadata abstract is never substituted for full text.

## Provenance and cache

Raw acquired PDF/HTML, normalized text and its SHA-256/page-span sidecar are stored
in the existing local cache and SQLite source records. Repeated remote inputs
reuse normalized content; internal `load_source(..., force_refresh=True)` refreshes
it. Cached remote content is a snapshot and may be stale. `verify_reference`
queries reference metadata anew; a claim using a bare DOI may reuse its existing
source snapshot without a registry request. The existing batch source/index reuse
and failure isolation apply.

Claim responses add `source_type`, `canonical_url` and `content_hash`. PDF evidence
retains physical page coordinates. HTML evidence has `page_start/page_end: null`
and `coordinate_system: normalized_html_text`; its offsets and quote refer to the
cached normalized article, not the publisher DOM. A synthetic page exists only
inside the chunking pipeline. `PASS` still requires exact verified provenance.

## Network and optional Unpaywall

DOI/citation fields leave the machine when sent to registries. Source servers
receive requested URLs and connection metadata. Claim inference remains local.
Unpaywall is optional and disabled until an email is configured:

```powershell
$env:CITATION_UNPAYWALL_EMAIL = "your-email@example.org"
```

The configured email is sent to Unpaywall as required by its API. No account,
token or fabricated email is automatically supplied. Restart the MCP client/server
after changing its environment. Unpaywall failure leaves publisher acquisition
available. All downloaded source text remains untrusted evidence.

Provider contracts: [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/),
[DataCite DOI retrieval](https://support.datacite.org/docs/how-do-i-query-the-rest-api-and-whats-in-the-response),
[Unpaywall API](https://unpaywall.org/api) and
[Unpaywall location fields](https://unpaywall.org/data-format).

No new third-party Python dependencies are introduced: HTML parsing, robots rules
and citation matching use the standard library; HTTP uses the existing requests
dependency. Existing V1 tools and NLI/numeric verdict thresholds remain unchanged.
