# Search-benchmark labels

One JSON or CSV file per question (`Q1.json`, `Q2.csv`, …). A second labeller
uses `Q1.<name>.json` (or CSV). Provider corpora stay out of this folder.

Columns: `key`, `title`, `labeller`, `category`, `rationale`, `work_type`,
`access_state`, `checked_at`, `inspection_depth`, `duplicate_of`, `split`,
`use_in_paper`.

`category` is one of: `direct_answer`, `mechanism_or_implementation`,
`experience_or_context`, `background`, `related_subject`, `incidental`,
`unclassified`. `split` is `dev` or `test`.
