.PHONY: check-public check-public-test

# Regression guard for the infra/content separation policy (auto-review-6mf.4).
# See docs/superpowers/specs/2026-06-27-infra-content-separation-design.md.
check-public:
	bash scripts/check-public.sh

# Self-test for the guard above: builds a throwaway git repo and asserts the
# guard fails on planted leaks and passes once clean/allowlisted.
check-public-test:
	bash scripts/check-public.test.sh
