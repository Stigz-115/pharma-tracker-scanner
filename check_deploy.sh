#!/usr/bin/env bash
# Diagnose why Streamlit Cloud may be building stale files.
# Run this INSIDE your local clone of the repo, on the branch Cloud deploys.
#
#   bash check_deploy.sh
#
# It verifies the three deploy-critical files are in the state that fixes the
# "installer returned a non-zero exit code" error, and checks that your local
# branch is actually pushed to the remote Cloud builds from.

set -u
fail=0
ok()   { printf "  \033[32mOK\033[0m   %s\n" "$1"; }
bad()  { printf "  \033[31mBAD\033[0m  %s\n" "$1"; fail=1; }
info() { printf "  ->   %s\n" "$1"; }

echo "== 1. packages.txt =="
if [ ! -f packages.txt ]; then
  ok "packages.txt absent (fine — no apt step at all)"
else
  bytes=$(wc -c < packages.txt | tr -d ' ')
  if [ "$bytes" -eq 0 ]; then
    ok "packages.txt is empty ($bytes bytes) — apt step will pass"
  else
    # empty-but-for-whitespace is also fine; real package names are the problem
    if grep -qE '^\s*lib|^\s*fonts|^\s*[a-z0-9]' packages.txt; then
      bad "packages.txt lists packages — this is what breaks apt on Debian trixie"
      info "contents:"; sed 's/^/       | /' packages.txt
      info "FIX: empty it ->  : > packages.txt   (or delete the file)"
    else
      ok "packages.txt has only whitespace — harmless"
    fi
  fi
fi

echo "== 2. requirements.txt =="
if grep -q 'playwright==1.49.0' requirements.txt 2>/dev/null; then
  ok "playwright pinned to 1.49.0"
else
  bad "playwright not pinned to 1.49.0"
  info "current: $(grep -i playwright requirements.txt || echo '(none)')"
fi

echo "== 3. app.py bootstrap order =="
if grep -q 'Step 1 — browser binary' app.py 2>/dev/null; then
  ok "ensure_chromium installs browser binary before apt deps"
else
  bad "app.py missing the binary-first bootstrap"
fi
if grep -qE '"install",[[:space:]]*"--with-deps"' app.py 2>/dev/null; then
  bad "app.py still calls 'install --with-deps' (couples browser DL to apt)"
else
  ok "no fragile 'install --with-deps' browser install in app.py"
fi

echo "== 4. git: is your fix actually pushed? =="
if git rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git branch --show-current)
  info "current branch: $branch"
  if git diff --quiet && git diff --cached --quiet; then
    ok "working tree clean (no uncommitted changes)"
  else
    bad "you have uncommitted changes — commit them before pushing"
    info "run: git add -A && git commit -m 'fix deploy'"
  fi
  # compare local HEAD to upstream
  if up=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null); then
    local_sha=$(git rev-parse HEAD)
    remote_sha=$(git rev-parse "@{u}" 2>/dev/null)
    if [ "$local_sha" = "$remote_sha" ]; then
      ok "local $branch is pushed and matches $up"
    else
      bad "local $branch is AHEAD of / differs from $up — you haven't pushed the fix"
      info "run: git push origin $branch"
    fi
  else
    bad "branch '$branch' has no upstream — Cloud may build a DIFFERENT branch"
    info "check Streamlit app Settings -> which branch it deploys"
    info "then: git push -u origin $branch"
  fi
  echo ""
  info "HEAD commit: $(git log -1 --oneline)"
  info "packages.txt in HEAD is $(git show HEAD:packages.txt 2>/dev/null | wc -c | tr -d ' ') bytes"
else
  bad "not a git repo — run this inside your clone"
fi

echo ""
if [ "$fail" -eq 0 ]; then
  printf "\033[32mAll deploy-critical checks passed.\033[0m If Cloud still errors, confirm the\n"
  printf "Streamlit app points at THIS repo + branch, then use 'Reboot app' (not just rerun).\n"
else
  printf "\033[31mFix the BAD items above, commit, push, then reboot the Streamlit app.\033[0m\n"
fi
exit $fail
