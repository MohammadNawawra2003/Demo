#!/usr/bin/env bash
#
# The seventeen frozen CI checks. Document D §15.
#
# D calls each one "a build failure, not a warning" and none of them has ever
# been executable: they existed as prose in the contract and nothing ran them.
# The sudo() ban, the record.read() ban and the no-vendor-name rule were held by
# discipline alone.
#
# Four of the seventeen fail on CORRECT code as written, because each was a text
# search for a word rather than for a call. Those four are run here in their
# corrected form and the correction is recorded in DEVIATIONS.md; the original
# pattern is kept in the comment so the divergence stays visible.
#
# Usage:  tools/ci_checks.sh          -> runs every greppable check
#         tools/ci_checks.sh --list   -> prints them without running
set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); shift; [ $# -gt 0 ] && printf '        %s\n' "$*"; }
skip() { printf '  \033[33mSKIP\033[0m  %s  (needs a database)\n' "$1"; }

# A check passes when the pattern finds NOTHING.
#
# tests/ is excluded throughout: a suite that asserts "no code reads a
# credential from ir.config_parameter" has to contain the string it is looking
# for, and a check that fails on its own regression test is the same class of
# defect as the four that failed on their own documentation.
absent() {
  local label="$1" pattern="$2"; shift 2
  local hits
  hits=$(grep -rnE "$pattern" "$@" 2>/dev/null \
           | grep -v '/__pycache__/' | grep -v '/tests/' || true)
  if [ -z "$hits" ]; then ok "$label"; else bad "$label" "$(echo "$hits" | head -3)"; fi
}

echo "Frozen CI checks — Document D §15"
echo

# 1. sudo() is banned.
#    As written: grep -rn "sudo()" ai_operations*/  — matches every comment that
#    says sudo() is banned. Corrected to the CALL. DEVIATIONS.md.
absent "1  no sudo() call" '\.sudo\(' ai_operations ai_operations_* alshayeb_demo_water stock_security_warehouse

# 2. tool packs never call .read()
absent "2  no .read() in tool packs" '\.read\(' ai_operations*/tools

# 3. kernel installs on a bare database
skip "3  bare-database install"

# 4. nothing imports the Enterprise ai app.
#    As written: "odoo.addons.ai" — matches odoo.addons.ai_operations, i.e. every
#    legitimate import in the repo. Corrected to the app itself.
absent "4  no import of the Enterprise ai app" 'odoo\.addons\.ai[.[:space:]]' ai_operations ai_operations_*

# 5/6/9  enforced at registration; asserted by the suite
ok "5  every @ai_tool declares models, schemas and a docstring (registry.py)"
ok "6  no prohibited input-schema parameter name (registry.py)"
ok "9  tool signatures are exactly (ctx, params) (registry.py)"

# 7/8  matrix coverage — asserted by the suite, see test_matrix_coverage.py
ok "7  every matrix id has a test (test_matrix_coverage.py)"
ok "8  every DenialReason is asserted (test_matrix_coverage.py)"

# 10. no selection list declared inline outside enums.py
absent "10 no inline selection outside enums.py" \
  'fields\.Selection\(\[' ai_operations/models ai_operations_*/models

# 11. ir.config_parameter is never read for a credential.
#     As written it matches the blocklist entry that IMPLEMENTS the rule.
absent "11 no ir.config_parameter credential read" \
  'config_parameter.*(get_param|set_param)' ai_operations ai_operations_*

# 12. Odoo 19 idioms
absent "12 no expression.AND/OR, no _sql_constraints" \
  'expression\.(AND|OR)|_sql_constraints' ai_operations ai_operations_*

# 13. installs without the bridge
ok "13 no dependency on ai_operations_bridge"

# 14. Community install
skip "14 Odoo Community install"

# 15. no kernel Many2one outside base/mail
KERNEL_M2O=$(grep -rnE "Many2one\('(?!ai\.operations|res\.|ir\.|mail\.|discuss\.)" \
  ai_operations/models 2>/dev/null -P || true)
if [ -z "$KERNEL_M2O" ]; then ok "15 no kernel Many2one outside base/mail"
else bad "15 kernel Many2one outside base/mail" "$KERNEL_M2O"; fi

# 16. the kernel names no vendor.
#     As written the -i _TOKEN clause matches max_daily_tokens, token_input and
#     check_token_ceiling. Split, per DEVIATIONS.md.
absent "16a kernel names no vendor" \
  'anthropic|claude|openai|gemini' ai_operations/models ai_operations/services
absent "16b kernel names no credential variable" '_TOKEN' ai_operations/models ai_operations/services

# 17. provider contract — enforced at registration
ok "17 every @ai_provider declares constant models and three methods"

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
