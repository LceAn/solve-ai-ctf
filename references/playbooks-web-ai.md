# Web and AI-Security Playbooks

## Contents

1. Web evidence model
2. Web workflow
3. Parser differentials
4. Authentication and workflow state
5. Deserialization, file, and cloud surfaces
6. Stop rules
7. AI-security workflow

## 1. Web evidence model

Model the application as layers:

```text
client → CDN/proxy/WAF → framework router → middleware → application
       → serializer/template/database/filesystem/object store/internal service
```

For every request, ask which layer decodes, normalizes, validates, authorizes, caches, and executes it. Many CTF Web bugs are disagreements between layers rather than a missing check in one layer.

Map:

- routes, methods, parameters, body formats, cookies, tokens, and redirects;
- identities, roles, objects, workspaces/tenants, and state transitions;
- source-map/JavaScript hints, error schemas, headers, version strings;
- normalization behavior for path, query, host, content type, and duplicate fields;
- external components such as MinIO/S3, queues, workers, and preview/conversion services.

## 2. Web workflow

1. Capture a clean baseline for every visible action.
2. Enumerate routes from HTML, JavaScript, OpenAPI/GraphQL, error messages, robots, and supplied source.
3. Build an authorization matrix: actor × action × object × workspace/state.
4. Diff one variable at a time: encoding, type, duplicate key, content type, path separator, case, or identity.
5. Prefer hints and architecture contradictions over generic payload lists.
6. Turn a promising manual request into a reproducible script with assertions.
7. Verify that the final response is from the intended backend path, not a mock, cached page, or decoy.

Test families only where inputs and evidence support them: injection, traversal, SSRF, template evaluation, deserialization, upload processing, JWT/session flaws, mass assignment, IDOR, race/TOCTOU, request smuggling, and business-logic/state confusion.

## 3. Parser differentials

Create a normalization matrix for a known safe resource and a controlled invalid resource:

- raw vs percent encoded vs double encoded;
- slash/backslash and mixed separators;
- dot segments and repeated separators;
- UTF-8 overlong/alternate Unicode where relevant;
- query vs path vs body placement;
- duplicate parameters and JSON keys;
- form, JSON, multipart, and alternate content types;
- proxy headers and absolute-form requests.

Record status, response length/hash, headers, timing, and semantic result. A differential is useful only when it distinguishes layers and supports a concrete exploit path.

The HK SeCAI corpus includes a decisive pattern: a WAF inspected one representation while a custom parser applied an additional decode, enabling a traversal. Generalize this as **cross-layer canonicalization**, not as one fixed payload.

## 4. Authentication and workflow state

Do not reduce auth testing to token cracking.

Model:

- registration fields and server-generated fields;
- login lookup vs password verification behavior;
- token claims vs database-derived role;
- object ownership, tenant/workspace binding, and server-side session state;
- import/attach/approve/run transitions;
- references such as profile keys, incident IDs, correlation IDs, and catalog IDs;
- error masking: “not found” may hide unauthorized.

Use paired accounts and paired objects. Test whether the server binds references to identity at creation, import, use, or not at all. Distinguish lookup failure from authorization failure with controlled existing/non-existing values when safe.

Brute-force stop rule: stop semantic key guessing when coverage is poorly defined, several independent candidate generators fail, or responses provide zero information gain. Pivot to permission checks, state construction, source/client recovery, parser behavior, or adjacent services.

## 5. Deserialization, file, and cloud surfaces

For pickle/serialization tasks:

- identify who creates and who consumes the object;
- map signing, validation, and storage boundaries;
- use a harmless proof first;
- inspect allowlists, reducers, import restrictions, and maintenance jobs;
- check whether file names, metadata, or object keys cross trust boundaries.

For upload/document pipelines:

- trace upload → storage → metadata → preview/conversion → download;
- inspect archive, XML/OOXML, image, PDF, and path handling;
- distinguish filename, MIME, magic, extension, and content validation;
- preserve benign fixtures and use minimal proofs.

For object stores/internal services:

- infer bucket/key patterns from client code and errors;
- test authorization at the application and storage layers separately;
- examine signed URL scope, tenant prefixes, metadata exposure, and server-side fetch behavior.

## 6. Stop rules

Pivot when:

- 20+ payloads test the same mechanism without a differential;
- the endpoint ignores the mutated field across controlled requests;
- the assumed secret appears cryptographically random and no leak/oracle exists;
- tool output is unreliable or unvalidated;
- the target/container has changed and prior baselines are stale.

Before declaring Web blocked, review client code, route inventory, auth matrix, parser matrix, adjacent services, and challenge wording. Record the exact missing fact.

## 7. AI-security workflow

### Threat model first

Identify the protected asset, attacker-controlled input, model/tool boundary, query budget, output channel, and success oracle.

### LLM/prompt/tool agents

- map system/developer/user/retrieval/tool-result trust boundaries;
- identify indirect prompt injection surfaces in files/pages/tool output;
- test instruction hierarchy, data exfiltration, tool misuse, and cross-session memory;
- use a payload taxonomy and mutate only after measuring baseline behavior;
- log full conversation and tool trace with secrets redacted;
- distinguish model refusal bypass from actual protected-asset disclosure.

### Model extraction/membership inference

- define fidelity or membership metric before querying;
- budget queries and select informative samples;
- compare against a baseline surrogate/attack;
- retain confidence intervals and avoid overclaiming from single examples.

### Adversarial examples

- capture preprocessing exactly;
- define norm, perturbation budget, targeted/untargeted objective, and allowed input range;
- verify the exported artifact through the same inference path;
- test transferability only if the challenge requires black-box behavior.

### Data poisoning

- map ingestion, labeling, deduplication, training, and evaluation;
- demonstrate the smallest causal poisoning set;
- separate training-time impact from ordinary inference-time injection.
