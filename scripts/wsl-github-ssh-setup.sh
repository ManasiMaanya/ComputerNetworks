#!/usr/bin/env bash
# Passwordless GitHub access from WSL via SSH (no GitHub password/PAT on each push).
set -euo pipefail

EMAIL="${GIT_SSH_EMAIL:-manasi.maanya@outlook.com}"
KEY="$HOME/.ssh/id_ed25519"

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -C "$EMAIL" -f "$KEY" -N ""
  echo "Created $KEY"
else
  echo "Using existing $KEY"
fi

chmod 600 "$KEY"
chmod 644 "${KEY}.pub"

CONFIG="$HOME/.ssh/config"
if [[ ! -f "$CONFIG" ]] || ! grep -q "Host github.com" "$CONFIG" 2>/dev/null; then
  cat >> "$CONFIG" << 'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
EOF
  echo "Wrote GitHub stanza in $CONFIG"
fi
chmod 600 "$CONFIG"

touch "$HOME/.ssh/known_hosts"
if ! grep -q github.com "$HOME/.ssh/known_hosts" 2>/dev/null; then
  ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
fi

# ssh-agent for this shell and future bash logins
eval "$(ssh-agent -s)" >/dev/null
ssh-add "$KEY" 2>/dev/null || true

if ! grep -q "ssh-add.*id_ed25519" "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" << 'EOF'

# GitHub SSH (ComputerNetworks)
if [ -z "$SSH_AUTH_SOCK" ]; then
  eval "$(ssh-agent -s)" >/dev/null
fi
ssh-add -l >/dev/null 2>&1 || ssh-add "$HOME/.ssh/id_ed25519" >/dev/null 2>&1
EOF
  echo "Added ssh-agent snippet to ~/.bashrc"
fi

echo
echo "----- PUBLIC KEY (add this at GitHub → Settings → SSH and GPG keys) -----"
cat "${KEY}.pub"
echo "----- end -----"
echo
echo "Then: git remote set-url origin git@github.com:ManasiMaanya/ComputerNetworks.git"
echo "Test: ssh -T git@github.com"
