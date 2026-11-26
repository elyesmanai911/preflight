# Ansible: configuring the demo VM

Terraform (`infra/demo`) creates the VM. Ansible configures it and keeps it configured.

| Role | What it does |
|---|---|
| `hardening` | SSH: keys only, `preflight` user only, no root. Firewall (ufw): deny inbound except 22 and 80, plus the k3s pod and service networks. Security updates install daily, without automatic reboots. |
| `k3s` | The pinned k3s release binary, verified against the release's checksum file, and its systemd unit. Waits for the node to be Ready. |
| `platform` | Argo CD (via k3s's Helm controller), the preview ApplicationSet on the VM's domain, Loki, Alloy and the triage watcher. |
| `secrets` | Reads the GitHub token and LLM key from Key Vault with the VM's managed identity and stores them as Kubernetes secrets. |

## Run it on the VM

`terraform apply` in `infra/demo` writes `inventory/demo.yml` (git-ignored), then:

```bash
ansible-playbook -i inventory/demo.yml site.yml
```

## Day 2: change the running VM without rebuilding it

| Task | How | Safety |
|---|---|---|
| Upgrade k3s | Bump `k3s_version` in `roles/k3s/defaults/main.yml` (PR), then `ansible-playbook -i inventory/demo.yml upgrade-k3s.yml` | The role refuses downgrades and skipped minor versions before touching anything. Afterwards the playbook checks that the node reports the new version and that DNS, Traefik and storage are available again. |
| Rotate a secret | New value into Key Vault with `TF_VAR_github_token=… terraform apply` in `infra/demo`, then `ansible-playbook -i inventory/demo.yml rotate-secrets.yml` | Terraform owns the value, so it can't drift back. The playbook then tests the new GitHub token and LLM key against their APIs. The triage CronJob picks them up on its next run. |
| Fix drift | `ansible-playbook -i inventory/demo.yml site.yml` | Idempotent: it only changes what differs. |

## Test locally (no Azure needed)

```bash
pip install ansible-core ansible-lint molecule "molecule-plugins[docker]"
ansible-galaxy collection install -r requirements.yml -p collections
ansible-lint
cd roles/hardening && ANSIBLE_COLLECTIONS_PATH=$PWD/../../collections molecule test && cd ../..
ANSIBLE_COLLECTIONS_PATH=$PWD/collections molecule test -s site      # the whole site.yml
ANSIBLE_COLLECTIONS_PATH=$PWD/collections molecule test -s upgrade   # day-2 k3s upgrade
```

Molecule builds an Ubuntu 24.04 container with systemd, applies the role, applies it a second
time to prove nothing changes (idempotence), then checks the state that is actually in effect:
`sshd -T`, `ufw status`, `apt-config dump`. The `site` scenario runs the real `site.yml` and
checks that the platform comes up: k3s version, Argo CD available, the ApplicationSet on the
right domain, the platform apps registered, and Traefik reachable on port 80 through the firewall.
Only `secrets` is skipped there, since it needs an Azure managed identity, and so is
`rotate-secrets.yml` (lint and syntax check only). The `upgrade` scenario installs the previous
minor version (v1.34), upgrades it with `upgrade-k3s.yml`, then checks that a downgrade and a
skipped minor version are both refused. CI runs the same steps on every PR.
