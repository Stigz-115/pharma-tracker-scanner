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
  ok "packages.txt absent — no system libs installed; only fine if Chromium's"
  info "     launch-time libs are already present in the base image"
else
  bytes=$(wc -c < packages.txt | tr -d ' ')
  if [ "$bytes" -eq 0 ]; then
    bad "packages.txt is empty — Chromium's launch will fail with"
    info "     'Host system is missing dependencies to run browsers'"
    info "FIX: list the exact package names Playwright's own launch error"
    info "     reports (it detects the container's actual Debian release)"
  else
    # Debian trixie renamed several of these with a t64 suffix
    # (e.g. libglib2.0-0 -> libglib2.0-0t64); the un-suffixed names produce
    # an unsatisfiable apt conflict ('held broken packages').
    if grep -qE '^\s*(libglib2\.0-0|libatk1\.0-0|libatk-bridge2\.0-0|libatspi2\.0-0|libasound2)\s*$' packages.txt; then
      bad "packages.txt lists OLD (pre-t64) package names — apt conflict on Debian trixie"
      info "contents:"; sed 's/^/       | /' packages.txt
      info "FIX: use the t64-suffixed names from Playwright's launch error"
    else
      ok "packages.txt has $(grep -cE '^\s*[a-z0-9]' packages.txt) package entries"
      info "contents:"; sed 's/^/       | /' packages.txt
    fi
  fi
fi

echo "== 2. requirements.txt =="
if grep -qE 'playwright==1\.49\.0' requirements.txt 2>/dev/null; then
  bad "playwright pinned to 1.49.0 — hard-pins greenlet==3.1.1, which has no"
  info "     prebuilt wheel for Python 3.14 and fails to compile against it"
  info "FIX: bump to playwright==1.55.0 (or newer) so greenlet resolves to a"
  info "     range (>=3.1.1,<4.0.0) and pip picks 3.2.x, which ships a cp314 wheel"
elif grep -q 'playwright' requirements.txt 2>/dev/null; then
  ok "playwright pin: $(grep -i playwright requirements.txt)"
else
  bad "no playwright entry in requirements.txt"
fi
if [ -f runtime.txt ]; then
  bad "runtime.txt present ($(cat runtime.txt)) — Streamlit Cloud has been seen"
  info "     ignoring this and building with its own default (currently 3.14"
  info "     on Community Cloud) regardless of what's pinned here. Don't rely"
  info "     on it; if you need a specific version, set it in the app's"
  info "     Settings -> Advanced UI instead, and make requirements.txt work"
  info "     under whatever Python Cloud actually gives you."
else
  ok "no runtime.txt — not fighting Cloud's actual (currently 3.14) default"
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
