# Azure setup

Provisioning Azure AI Search and Document Intelligence for this project, and
what each one actually does at request time.

Prerequisite: an **Azure subscription**. `az login` succeeding is not enough —
if it prints *"No subscriptions found"* you have an Entra identity but nothing
to create resources in. Sign up at
[azure.microsoft.com/free](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account)
($200 credit for 30 days; a card is required for identity verification only).
Before assuming you have none, check whether one exists in another tenant:

```powershell
az login --allow-no-subscriptions
az account tenant list --output table
az account list --all --output table
```

---

## 1. What these services do at request time

Understanding this first makes the tier choices obvious.

### Document Intelligence — ingestion only, never on the query path

One call per document, at ingest time:

```
POST {endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze
  → 202 Accepted + an operation URL
  → poll until succeeded (seconds to minutes for a long filing)
  → JSON: paragraphs[] with roles and page numbers,
           tables[] with cells carrying rowIndex/columnIndex/spans,
           pages[] with bounding regions
```

`prebuilt-layout`, not `prebuilt-read`, and the difference is the whole reason
this service is here:

- **Tables as structured cells**, not flattened text. A balance sheet survives
  as rows and columns, which is what `tables.py` needs to stitch a page-split
  table back together.
- **Section headings with hierarchy** — the chunk boundaries `chunking.py`
  splits on.
- **Bounding regions** — what lets a citation resolve to a page and a highlight
  box rather than just a filename.

It is a long-running operation, which is why ingestion is a **job** and not an
endpoint, and why the parsed result is cached to disk before chunking: parsing
is the slow, billed, non-deterministic step.

### AI Search — the query path

One call per question:

```
POST {endpoint}/indexes/filings/docs/search?api-version=...
{
  "search":        "how did gross margin change",   ← BM25
  "vectorQueries": [{ "kind":"vector", "vector":[...], "fields":"content_vector" }],
  "filter":        "(fiscal_year eq 2023)",         ← applied BEFORE ranking
  "queryType":     "semantic",                      ← reranker (Basic+ only)
  "top": 8
}
```

The critical property: **that is one request, not two.** Sending both `search`
and `vectorQueries` makes the service run BM25 and vector search and fuse them
with Reciprocal Rank Fusion server-side. You never merge two result sets in
application code. Adding `queryType: semantic` then re-scores the fused top
results with a Microsoft-hosted cross-encoder.

`filter` is evaluated *before* ranking, which is why extracting ticker and
fiscal year from the question matters so much — it scopes the candidate set
instead of hoping the ranker sorts out the wrong company.

---

## 2. Choosing tiers

| | Free | Paid | Recommendation |
|---|---|---|---|
| **AI Search** | 50 MB, 3 indexes, 1 per subscription. BM25 **and vectors work**. **No semantic ranker.** | Basic ≈ $75/mo, 15 GB, semantic ranker | **Start Free.** Three of four ablation arms work. |
| **Document Intelligence** | F0: 500 pages/month, but **only the first 2 pages of any document**, 4 MB cap | S0: pay per page, ~$10 per 1,000 pages for layout | **F0 to smoke-test, S0 for a real corpus** |

Two consequences worth internalising:

**Free-tier Search cannot do the semantic ranker.** Set
`ENABLE_SEMANTIC_RANKER=false`, or index creation defines a semantic
configuration the service can never serve and `hybrid_semantic` queries fail at
query time. You still get `vector_only`, `bm25_only` and `hybrid_rrf`.

**F0 Document Intelligence is useless for filings.** A 10-K is 100+ pages and
F0 reads two of them, so you would index the cover page and nothing else. Use
it to prove the wiring works, then switch to S0 with a deliberately small
corpus — 15 filings at ~80 pages is ~1,200 pages, on the order of $12.

Free → Basic is **not** an in-place upgrade on Search; you create a new service
and re-index. Plan to stay on Free until you specifically want the reranker
number for the ablation table.

---

## 3. Provisioning

```powershell
# Pick names: search service names are globally unique, lowercase.
$RG       = "rg-finrag-dev"
$LOCATION = "eastus"
$SEARCH   = "finrag-dev-search-<yourinitials>"
$DOCINTEL = "finrag-dev-docintel-<yourinitials>"

az group create --name $RG --location $LOCATION

# --- AI Search, Free tier -------------------------------------------------
az search service create `
  --name $SEARCH --resource-group $RG `
  --sku free --location $LOCATION

# --- Document Intelligence ------------------------------------------------
# --custom-domain is REQUIRED for Entra ID auth, which is what this app uses.
# Use --sku F0 to smoke-test, --sku S0 for a real corpus.
az cognitiveservices account create `
  --name $DOCINTEL --resource-group $RG `
  --kind FormRecognizer --sku S0 --location $LOCATION `
  --custom-domain $DOCINTEL --yes
```

### Enable Entra ID auth on Search

Search defaults to API-key auth. This app authenticates as an identity, so
switch it to accept both. In the **portal** (most reliable):

> Search service → **Settings → Keys** → *API access control* → **Both**

Or via CLI:

```powershell
az search service update --name $SEARCH --resource-group $RG `
  --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge
```

### Grant your own account the data-plane roles

Being subscription owner is **not** enough — Search and Cognitive Services
data-plane access is granted by separate RBAC roles. Locally you authenticate
as yourself via `az login`; in Azure the container app uses its managed
identity with these same roles.

```powershell
$ME         = az ad signed-in-user show --query id -o tsv
$SEARCH_ID  = az search service show -n $SEARCH -g $RG --query id -o tsv
$DOCINTEL_ID= az cognitiveservices account show -n $DOCINTEL -g $RG --query id -o tsv

# Read/write documents in the index
az role assignment create --assignee $ME `
  --role "Search Index Data Contributor" --scope $SEARCH_ID

# Create and update the index definition itself
az role assignment create --assignee $ME `
  --role "Search Service Contributor" --scope $SEARCH_ID

# Call the Document Intelligence analyze API
az role assignment create --assignee $ME `
  --role "Cognitive Services User" --scope $DOCINTEL_ID
```

Role assignments can take a minute or two to propagate. A `403` immediately
after creating them usually means "wait", not "wrong role".

---

## 4. Configure and verify

Get the endpoints:

```powershell
az search service show -n $SEARCH -g $RG --query "hostName" -o tsv
az cognitiveservices account show -n $DOCINTEL -g $RG --query "properties.endpoint" -o tsv
```

`backend/.env`:

```bash
SEARCH_BACKEND=azure
PARSER_BACKEND=azure

SEARCH_ENDPOINT=https://<your-search-name>.search.windows.net
SEARCH_INDEX=filings
ENABLE_SEMANTIC_RANKER=false          # true only on Basic or above

DOC_INTELLIGENCE_ENDPOINT=https://<your-docintel-name>.cognitiveservices.azure.com/

GEMINI_API_KEY=your-key
ENABLE_EMBEDDINGS=true
EMBED_DIMS=1536
DEFAULT_CONFIG_ID=hybrid_rrf          # hybrid_semantic needs Basic+
```

Then, in order — each step verifies the previous one:

```bash
cd backend
pip install -e ".[api,gemini,azure,dev]"

python -m apps.ingest.main --check          # config + connectivity
python -m apps.ingest.main --create-index   # creates 'filings'
python -m apps.ingest.main --local ./corpus # PDFs now, not markdown
python -m apps.ingest.main --check          # should report a document count
```

`--check` probes each dependency separately and reports failures rather than
raising, so one broken thing does not hide the state of the others.

Get real filings from [SEC EDGAR](https://www.sec.gov/edgar/searchedgar/companysearch)
— **start with 2 or 3**, confirm the chunk count and a query look sane, and only
then ingest the rest. Parsing is the billed step and the parsed cache means a
re-run costs nothing, but a bad first run costs pages.

---

## 5. Troubleshooting

| Symptom | Cause |
|---|---|
| `No subscriptions found` on `az login` | No subscription on the account, or it lives in another tenant — see the top of this page |
| `403` from Search | Missing data-plane role, or API access control not set to **Both**. Owner ≠ data access |
| `401` from Document Intelligence | `--custom-domain` was not set at creation; Entra auth requires it |
| Index creation fails on semantic config | Free tier — set `ENABLE_SEMANTIC_RANKER=false` |
| Only 2 pages of each PDF parsed | Document Intelligence is on F0. Move to S0 |
| Vector field dimension error | `EMBED_DIMS` changed after the index was created. Dimensions are fixed at creation — use a new index name and re-embed |
| Storage quota exceeded on Search | Free tier is 50 MB total. Reduce the corpus or move to Basic |

---

## 6. What changes versus local mode

| | Local | Azure |
|---|---|---|
| Fusion | RRF computed in `local_search.py` | RRF server-side, one request |
| Reranking | none | semantic ranker (Basic+) |
| Parsing | markdown/text only | real PDF layout, tables, bounding regions |
| Citations | page number only | page + bounding box for highlighting |
| Scale | one JSON file in memory | 24 billion docs/index on Basic |

Quality numbers measured locally are **not** comparable to Azure ones — the
retrieval stack is genuinely different. Re-run the eval harness after moving,
and treat the local numbers as a smoke test rather than a baseline.
