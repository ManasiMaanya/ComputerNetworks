# Passwordless Git from WSL (GitHub SSH)

Git in WSL talks to GitHub over **SSH**. You prove who you are with a key, not a GitHub password. The **private** key stays in WSL (`~/.ssh/id_ed25519`) — never copy it into this repo.

## One-time setup

1. In WSL:

```
chmod +x /mnt/c/Users/manas/VIT/ComputerNetworks/scripts/wsl-github-ssh-setup.sh
/mnt/c/Users/manas/VIT/ComputerNetworks/scripts/wsl-github-ssh-setup.sh
```

2. Copy the **public** key line (`ssh-ed25519 AAAA...`).

3. In the browser (logged into GitHub as **ManasiMaanya**):
   - [SSH and GPG keys](https://github.com/settings/keys)
   - **New SSH key**
   - Title: `WSL`
   - Key type: **Authentication Key**
   - Paste the public key → **Add SSH key**

4. Point this repo at SSH (from WSL, in the project folder):

```
cd /mnt/c/Users/manas/VIT/ComputerNetworks
git remote set-url origin git@github.com:ManasiMaanya/ComputerNetworks.git
ssh -T git@github.com
```

Expected: `Hi ManasiMaanya! You've successfully authenticated...` (exit code 1 is normal for `-T`).

5. Push without a password:

```
git push
```

## If it still asks for a password

- You are still on **HTTPS** (`https://github.com/...`). Repeat step 4.
- The public key is not on the GitHub account that owns the repo.
- Test: `ssh -vT git@github.com` and look for `Offering public key`.

## HTTPS instead of SSH

Use a **Personal Access Token** as the password, plus Git Credential Manager. SSH is simpler for WSL.

## Windows Git vs WSL Git

This key lives in **WSL** (`/home/manasi/.ssh/`). Cursor/PowerShell on Windows uses a different Git unless you open a WSL terminal. For passwordless **Windows** Git, add the same **public** key (or a second key) in Windows `C:\Users\manas\.ssh\` the same way, or use GitHub’s Git Credential Manager.
