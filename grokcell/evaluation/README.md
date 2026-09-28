# Evaluation preparation (no scored runs)

These files freeze the questions and record format before any scored evaluation.
They contain development fixtures only. No Jev/HF request, paid run, candidate
execution, sealed evaluation case, real maintainer observation, or comparative
result is included.

## Studies

- `study_a.json` compares fixed, Jev, and a pre-registered inexpensive
  alternative controller. All arms must use the same worker, verifier,
  environment, authority, limits, case order, and retry policy. Controller
  identity, version, date, and cost basis are recorded before evaluation.
- `study_b.json` compares complete systems against the same task outcomes,
  evidence bar, permitted authority, and resource envelope. It does not require
  systems to use the same decomposition or controller.

An independent acceptance owner, identified outside this package, controls the
sealed cases and signs the exact case-set commitment. Neither study may score
until that owner, case families, repository split, and separately authorized
execution envelope are recorded. Development, retrieval, and evaluation cases
must remain disjoint by both case family and repository. No sealed case is
stored in this checkout.

## Records and summaries

Supply one JSON object per line to `validate_results.py`. Every attempt,
including failed and unresolved attempts, belongs in the record. The validator
requires a separate private case registry from the independent owner, enforces
case-family/repository split isolation, and for Study A requires all three arms
with matching worker, checks, environment, authority, and limits. It emits
descriptive totals for attempts, failures,
coverage, human rescue, latency, known cost, unreconciled cost, and uncertainty.
It does not run candidate code, contact providers, impute unknown values, or
declare a winner. A validation pass proves only that the supplied record is
well-formed; evidence authenticity and case secrecy remain with the independent
acceptance owner.

Example local command (with a future approved result file):

```text
python grokcell/evaluation/validate_results.py path/to/results.jsonl --registry path/to/private-case-registry.json --study A
```

There is intentionally no result file in this package. The public one-action
fixture remains a negative control; development fixtures are not sealed cases
and cannot establish comparative performance.

The operator guide's adapter descriptions were checked against the source and
current provider documentation on 2026-09-26: TypeSafe documents fixed-option
Choice requests and returned choice/probability/confidence fields
([Choice](https://docs.typesafe.ai/primitives/choice),
[API reference](https://docs.typesafe.ai/api)); Hugging Face documents its
OpenAI-compatible routed Chat Completion endpoint
([task documentation](https://huggingface.co/docs/inference-providers/tasks/chat-completion)).
This confirms interface shape only, not current account access, model service,
price, or any live result.
