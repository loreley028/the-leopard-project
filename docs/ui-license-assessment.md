# UI license assessment

## Current decision

`animal-island-ui` 1.3.0 is approved for the current `private_noncommercial_research` scope under CC BY-NC 4.0. The current users are the project owner and a few friends, expected to remain within approximately ten people.

The current scope is not company or enterprise use, a paid product, a commercial service, a template offered for sale, an advertising business or a subscription business. There is no direct or indirect commercial revenue. This record is an engineering scope gate, not legal advice or a substitute for permission from the rights holder.

## Conditions of use

- Pin the npm dependency to exactly `1.3.0`; do not use a floating range.
- Attribute author guokaigdg, link the [original project](https://github.com/guokaigdg/animal-island-ui), and link the [CC BY-NC 4.0 license](https://creativecommons.org/licenses/by-nc/4.0/).
- State that The Leopard Project integrates and locally adapts layout, business styling and interactions through its Island adapter layer.
- Do not imply endorsement, sponsorship, authorization or affiliation by the author or Nintendo.
- Do not copy the component repository source or its distribution into this repository and do not add it as a Git submodule.
- Do not use Nintendo characters, logos, game screenshots, official audio, official icons or official art assets.

The npm metadata, package LICENSE and repository LICENSE at the npm release commit all identify CC BY-NC 4.0. The installed package ships `AI_USAGE.md`, but its heading still says `v0.9.5` while the package is `1.3.0`; therefore actual `dist/types` declarations are the final API authority. This documentation-version drift is a maintenance risk, not a license mismatch.

## Mandatory re-review triggers

The approval automatically closes and a new license review is required before any of the following: company-internal use, enterprise deployment, expansion from private friends to public users, public registration, paid access, advertising, subscription, sale, commercial partnership, or any direct or indirect commercial benefit.

The machine-readable scope is recorded in `config/ui_dependency_policy_v1.json`. That configuration records the current decision; it does not create legal rights.

`ui_third_party_asset_review_pending` remains an explicit maintenance item: the fonts and graphical resources distributed through the upstream package must receive a new provenance and rights review before any public, enterprise or commercial use.
