# Continuous integration

`.github/workflows/ci.yml` runs on `pull_request` and `push` with only `contents: read` permission.

The job:

1. checks out the repository;
2. installs Python 3.12 and `.[dev]`;
3. runs `pytest -p no:cacheprovider -m "not live"`;
4. parses and validates the workflow YAML and permission policy;
5. validates Phase 0, Phase 1A, and Phase 1B-0 policies;
6. validates all checked JSON;
7. compiles Python with its cache redirected outside the checkout;
8. checks tracked and candidate paths, file sizes, and credential patterns;
9. fails if any CI step changed or added a file in the checkout.

CI contains no secrets reference, no Token, no cloud access, no repository write permission, and no live-test opt-in. GitHub documents that explicitly setting `contents: read` makes unspecified token permissions `none`; see [GitHub workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions).

Live tests retain the `live` marker and require `LEOPARD_RUN_LIVE=1`; they are manual diagnostics outside CI.
