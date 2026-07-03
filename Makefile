.PHONY: check-public

# Regression guard for the infra/content separation policy (auto-review-6mf.4).
# See docs/superpowers/specs/2026-06-27-infra-content-separation-design.md.
check-public:
	bash scripts/check-public.sh
