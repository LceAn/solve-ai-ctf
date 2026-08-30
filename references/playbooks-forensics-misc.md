# Forensics and Misc Playbooks

## Contents

1. Forensics principles
2. Packet captures
3. Filesystems and storage
4. File and media analysis
5. Encoding and container chains
6. Puzzle and interactive tasks
7. Verification

## 1. Forensics principles

Preserve originals, hash them, and write derived artifacts elsewhere. Record every transformation as an edge in a derivation graph:

`input_hash --tool/version/parameters--> output_hash`

Start with representation census: file magic, size, entropy, strings, metadata, timestamps, embedded signatures, protocol counts, and repeated structure. Do not mount or modify an original image read-write.

## 2. Packet captures

Build protocol statistics before filtering. Examine:

- dominant protocols, endpoints, ports, time windows, and packet sizes;
- DNS labels, HTTP objects, TLS metadata, ICMP payloads, and custom TCP streams;
- sequence numbers in labels or payloads;
- missing/duplicate chunks;
- alphabet and entropy of extracted fields;
- whether sorting by capture order or embedded index is correct.

For suspected DNS tunnels, group by domain, extract the data-bearing label, validate sequence coverage, normalize case/padding, then decode. Preserve the raw ordered stream before further transformation.

## 3. Filesystems and storage

### Filesystem images

- identify filesystem and geometry;
- parse metadata and deleted entries with forensic tools;
- search names, headers, and slack/unallocated space;
- inspect data runs and recover files to a separate directory;
- look for stride/interleaving when visible characters repeat at fixed offsets.

When a flag is dispersed every `n` bytes, derive the stride from autocorrelation/visible prefixes instead of hardcoding one observed offset.

### RAID

Do not assume missing-disk recovery is simply `disk1 XOR disk2`. Determine:

- RAID level and member count;
- stripe/chunk size;
- member order;
- parity rotation/layout;
- missing member position;
- filesystem alignment and superblocks.

Enumerate plausible layouts and score reconstructed images by filesystem magic, structural checks, and mountability. XOR parity is the primitive; correct interleaving is the solve.

## 4. File and media analysis

Use staged analysis:

1. magic and metadata;
2. strings and embedded headers;
3. archive/member listing;
4. steganography/media-specific analysis;
5. carving and repair;
6. OCR/barcode/audio-spectrum only when supported.

Office documents are ZIP/XML containers; PDFs may hold attachments, JavaScript, forms, or incremental updates. Open suspicious documents only in isolation and inspect structure first.

## 5. Encoding and container chains

Represent a chain as nodes with measurable properties:

| Stage | Length | Charset | Entropy | Magic/validation |
|---|---:|---|---:|---|
| extracted labels | ... | A-Z2-7 | ... | Base32 candidate |
| decoded text | ... | 58 symbols | ... | custom Base58 |
| decoded bytes | ... | binary | ... | ZIP magic |

At each step:

- preserve input/output;
- state why the transform is selected;
- validate padding/alphabet/order;
- check output magic and parsability;
- stop automatic recursion when multiple transforms are plausible.

For custom Base-N alphabets, infer the symbol set separately from the ordering. Enumerate justified order families and score outputs by magic/structure rather than printable text alone.

Encrypted legacy ZIP may be vulnerable to known-plaintext attacks when content is stored and a predictable file header provides enough consecutive bytes. Confirm encryption method and compression mode before invoking a cracking tool.

## 6. Puzzle and interactive tasks

### Puzzles

Extract entities and relations into a graph/table. Separate clue text from distractor text. Test common structures—acrostics, indexing, word lengths, semantic relations, ordering—using explicit scoring. Avoid endless literary interpretation without a falsifiable rule.

### Interactive computation

- capture protocol and sample rounds;
- identify invariant and complexity bound;
- implement parser/solver separately;
- add timeout and reconnect logic;
- validate answers locally on generated instances;
- keep exact integer/float formatting.

### OSINT

Use only when the challenge clearly authorizes external research. Preserve citations and timestamps. Do not leak team accounts or search with sensitive tokens.

## 7. Verification

For every derived flag candidate, retain the complete transformation chain and hashes. A screenshot/OCR result should be confirmed visually and, if possible, by a second extraction method. A carved file must pass format validation before its contents are trusted.
